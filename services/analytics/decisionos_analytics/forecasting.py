"""M2 Forecasting Lab (spec §16): suitability checks, baseline-first model
selection, holdout evaluation, and prediction intervals.

Design principles encoded here:
1. History can support a forecast but never guarantees one — every result
   carries explicit assumptions, evaluation metrics, and limitations.
2. A complex model must earn its place: Auto* candidates are selected only
   when they beat the simplest baseline (Naive/SeasonalNaive) on holdout MASE
   by a meaningful margin; otherwise the baseline wins.
3. Refusal is a first-class outcome: too little history yields
   insufficient_data with the additional data needed — never a fabricated
   forecast (§16.4).

Model specs are JSON-safe (the fitted state is re-derived from the stored
series at predict time), so they persist in the SQLite control store and
travel through the API without pickles.
"""

import json
import math
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
import polars as pl
from statsforecast import StatsForecast
from statsforecast.models import AutoARIMA, AutoETS, AutoTheta, Naive, SeasonalNaive

from .evidence import compute_canonical_digest
from .execution import _parse_ts, _pred
from .semantics import (
    CountExpression,
    DurationPercentileExpression,
    MetricDefinitionContent,
    RatioExpression,
)
from .store import Store, new_id, now_iso

MIN_PERIODS = 12  # §16.4: refuse below this
BASELINE_MODELS = ("Naive", "SeasonalNaive")
CANDIDATE_MODELS = ("Naive", "SeasonalNaive", "AutoTheta", "AutoETS", "AutoARIMA")
# complexity rank: simpler first; used for the "complex must earn its place" rule
COMPLEXITY = {name: i for i, name in enumerate(CANDIDATE_MODELS)}
COMPLEXITY_MARGIN = 0.02  # a complex model must improve MASE by >2% over baseline

FREQ_TRUNCATE = {"D": "1d", "W": "1w", "MS": "1mo", "H": "1h"}
FREQ_PANDAS = {"D": "D", "W": "W", "MS": "MS", "H": "h"}
DEFAULT_SEASON = {"D": 7, "W": 52, "MS": 12, "H": 24}

ASSUMPTIONS = [
    "future periods follow the same process that generated the training window",
    "values are complete aggregates per period; gaps were interpolated, not imputed by a model",
    "prediction intervals come from the model's residual distribution (80% and 95%)",
]
LIMITATIONS = [
    "accuracy is expected to degrade as the horizon grows beyond the evaluated holdout",
    "no causal drivers are modeled; external shocks (campaigns, outages, policy changes) invalidate the forecast",
    "counts on a seasonal baseline can lag structural breaks by one full season",
]


class ForecastRefused(Exception):
    """Refusal with the additional data needed (§16 workflow step 1)."""

    def __init__(self, reason: str, missing: list[str] | None = None, actions: list[str] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.missing = missing or []
        self.actions = actions or []


# --------------------------------------------------------------------------
# series plumbing
# --------------------------------------------------------------------------

def _as_frame(data: pl.DataFrame, time_col: str = "ds", value_col: str = "y") -> pl.DataFrame:
    if time_col not in data.columns or value_col not in data.columns:
        raise ForecastRefused(
            "series not found",
            missing=[f"columns {time_col} and {value_col}"],
            actions=["aggregate the metric per period before forecasting"],
        )
    df = data.select(
        pl.col(time_col).cast(pl.Datetime("us"), strict=False).alias("ds"),
        pl.col(value_col).cast(pl.Float64, strict=False).alias("y"),
    ).filter(pl.col("ds").is_not_null() & pl.col("y").is_not_null())
    if df.height == 0:
        raise ForecastRefused("no usable observations", missing=["non-null (time, value) pairs"], actions=["check the time basis and value column"])
    return df.group_by("ds", maintain_order=True).agg(pl.col("y").mean()).sort("ds")


def _to_pandas(df: pl.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "unique_id": "m1",
            "ds": pd.to_datetime([d.isoformat() for d in df["ds"].to_list()]),
            "y": df["y"].to_list(),
        }
    )


def build_metric_series(
    frame: pl.DataFrame,
    defn: MetricDefinitionContent,
    frequency: str = "D",
    season_length: int | None = None,
    max_buckets: int = 730,
) -> pl.DataFrame:
    """Aggregate a certified metric into a per-period (ds, y) series.

    Empty buckets are dropped (suitability reports coverage); this keeps the
    series honest — we never invent zero-volume periods the data doesn't show.
    """
    if frequency not in FREQ_TRUNCATE:
        raise ForecastRefused(f"unsupported frequency {frequency}", actions=[f"use one of {sorted(FREQ_TRUNCATE)}"])
    df = frame.with_columns(_parse_ts(defn.time_basis).alias("_tb")).filter(pl.col("_tb").is_not_null())
    for p in defn.eligibility:
        df = df.filter(_pred(p))
    df = df.with_columns(pl.col("_tb").dt.truncate(FREQ_TRUNCATE[frequency]).alias("ds"))

    expr = defn.expression
    if isinstance(expr, RatioExpression):
        num = expr.numerator_predicates
        den = expr.denominator_predicates
        num_e = pl.len() if not num else _and_cast(num)
        den_e = pl.len() if not den else _and_cast(den)
        agg = [num_e.alias("_num"), den_e.alias("_den")]
    elif isinstance(expr, DurationPercentileExpression):
        div = {"hours": 3600.0, "minutes": 60.0, "days": 86400.0}[expr.unit]
        dur = (_parse_ts(expr.end_field) - _parse_ts(expr.start_field)).dt.total_seconds() / div
        df = df.with_columns(dur.alias("_dur"))
        agg = [pl.col("_dur").quantile(expr.quantile, interpolation="linear").alias("y")]
    elif isinstance(expr, CountExpression):
        agg = [(_and_cast(expr.predicates) if expr.predicates else pl.len()).alias("y")]
    else:  # pragma: no cover
        raise ForecastRefused("unsupported expression kind")

    res = df.drop_nulls("ds").group_by("ds", maintain_order=True).agg(agg)
    if isinstance(expr, RatioExpression):
        res = res.with_columns(
            pl.when(pl.col("_den") == 0).then(None).otherwise(pl.col("_num") / pl.col("_den")).alias("y")
        ).drop("_num", "_den")
    res = res.filter(pl.col("y").is_not_null()).sort("ds")
    if res.height > max_buckets:
        res = res.tail(max_buckets)  # bounded history keeps refit-at-predict cheap and deterministic
    return res.select("ds", "y")


def _and_cast(preds) -> pl.Expr:
    e = pl.lit(True)
    for p in preds:
        e = e & _pred(p)
    return e.cast(pl.Int64).sum()


# --------------------------------------------------------------------------
# suitability
# --------------------------------------------------------------------------

def check_suitability(data: pl.DataFrame, min_periods: int = MIN_PERIODS, time_col: str = "ds", value_col: str = "y") -> dict:
    """Does the available data support the requested prediction? (§16 workflow 1)."""
    df = _as_frame(data, time_col, value_col)
    n = df.height
    warnings: list[str] = []
    actions: list[str] = []

    if n < min_periods:
        return {
            "sufficient": False,
            "reason": f"only {n} complete periods observed; forecasting requires at least {min_periods}",
            "observations": n,
            "coverage": None,
            "warnings": [],
            "recommended_actions": [
                f"upload history covering at least {min_periods} periods",
                "or aggregate to a coarser frequency (e.g. weekly/monthly buckets)",
            ],
        }

    steps = df["ds"].diff().drop_nulls()
    if steps.len() > 0:
        median_step = steps.median()  # timedelta
        span = df["ds"].max() - df["ds"].min()
        expected = int(span.total_seconds() // median_step.total_seconds()) + 1 if median_step and median_step.total_seconds() else n
        coverage = round(n / expected, 4) if expected else 1.0
        if coverage < 0.8:
            warnings.append(f"coverage is {coverage:.0%} of the calendar span; missing periods were skipped, not zero-filled")
            actions.append("backfill or re-upload the missing periods for a more reliable forecast")
    else:
        coverage = 1.0

    if df["y"].std() == 0:
        warnings.append("series is constant; a forecast would only restate the current level")
        actions.append("verify the metric actually varies over the window")

    return {
        "sufficient": True,
        "reason": None,
        "observations": n,
        "coverage": coverage,
        "warnings": warnings,
        "recommended_actions": actions or ["proceed to baseline evaluation"],
    }


# --------------------------------------------------------------------------
# models + evaluation
# --------------------------------------------------------------------------

def _make_model(name: str, season_length: int):
    m = max(1, int(season_length))
    match name:
        case "Naive":
            return Naive()
        case "SeasonalNaive":
            return SeasonalNaive(m)
        case "AutoTheta":
            return AutoTheta(season_length=m)
        case "AutoETS":
            return AutoETS(season_length=m)
        case "AutoARIMA":
            return AutoARIMA(season_length=m)
        case _:
            raise ForecastRefused(f"unknown model {name}")


def _metrics(actual: np.ndarray, pred: np.ndarray, train_y: np.ndarray, m: int) -> dict:
    err = actual - pred
    mae = float(np.mean(np.abs(err))) if err.size else None
    rmse = math.sqrt(float(np.mean(err**2))) if err.size else None
    nz = actual != 0
    mape = float(np.mean(np.abs(err[nz] / actual[nz])) * 100) if nz.any() else None
    diffs = np.abs(np.diff(train_y, n=1)) if train_y.size > 1 else np.array([])
    if m > 1 and train_y.size > m:
        diffs = np.abs(train_y[m:] - train_y[:-m])
    scale = float(np.mean(diffs)) if diffs.size else 0.0
    # MASE denominator must be derived ONLY from fold training data.
    # If scale == 0: mase = None (undefined). Never return 0 or infinity.
    mase = float(np.mean(np.abs(err)) / scale) if scale > 0 else None
    return {"mae": _r(mae), "mape": _r(mape), "mase": _r(mase), "rmse": _r(rmse)}


def pinball_loss(actual: np.ndarray, pred_q: np.ndarray, q: float) -> float | None:
    """Calculate quantile loss (pinball loss) for quantile q in (0, 1)."""
    if actual.size == 0 or pred_q.size == 0 or np.isnan(pred_q).all():
        return None
    err = actual - pred_q
    loss = np.maximum(q * err, (q - 1.0) * err)
    return _r(float(np.mean(loss)))


def validate_forecast_intervals(
    yhat: np.ndarray,
    lo95: np.ndarray,
    hi95: np.ndarray,
    lo80: np.ndarray | None = None,
    hi80: np.ndarray | None = None,
) -> dict[str, Any]:
    """Validate prediction intervals: lower <= point <= upper and quantile nesting (lo95 <= lo80 <= yhat <= hi80 <= hi95)."""
    valid_bounds = True
    valid_nesting = True

    if not (np.all(np.isnan(lo95) | (lo95 <= yhat + 1e-9)) and np.all(np.isnan(hi95) | (yhat <= hi95 + 1e-9))):
        valid_bounds = False

    if lo80 is not None and hi80 is not None:
        cond = (
            np.all(np.isnan(lo95) | np.isnan(lo80) | (lo95 <= lo80 + 1e-9))
            and np.all(np.isnan(lo80) | (lo80 <= yhat + 1e-9))
            and np.all(np.isnan(hi80) | (yhat <= hi80 + 1e-9))
            and np.all(np.isnan(hi80) | np.isnan(hi95) | (hi80 <= hi95 + 1e-9))
        )
        if not cond:
            valid_nesting = False

    return {
        "valid_bounds": valid_bounds,
        "valid_nesting": valid_nesting,
        "valid": valid_bounds and valid_nesting,
    }


def _r(v: float | None) -> float | None:
    return None if v is None or not math.isfinite(v) else round(v, 6)


def _fit_predict(train: pl.DataFrame, name: str, m: int, frequency: str, h: int) -> np.ndarray:
    sf = StatsForecast([_make_model(name, m)], freq=FREQ_PANDAS[frequency], n_jobs=1)
    sf.fit(_to_pandas(train))
    out = sf.predict(h=h)
    col = out[f"{name}"] if name in out.columns else out.iloc[:, 2]
    return np.asarray(pd.to_numeric(col, errors="coerce").to_numpy(), dtype=float)


def _fit_predict_with_intervals(
    train: pl.DataFrame, name: str, m: int, frequency: str, h: int
) -> dict[str, np.ndarray]:
    sf = StatsForecast([_make_model(name, m)], freq=FREQ_PANDAS[frequency], n_jobs=1)
    sf.fit(_to_pandas(train))
    out = sf.predict(h=h, level=[80, 95])
    yhat = pd.to_numeric(out[name], errors="coerce").to_numpy(dtype=float)
    lo95 = pd.to_numeric(out.get(f"{name}-lo-95", np.nan), errors="coerce").to_numpy(dtype=float) if f"{name}-lo-95" in out.columns else np.full(h, np.nan)
    hi95 = pd.to_numeric(out.get(f"{name}-hi-95", np.nan), errors="coerce").to_numpy(dtype=float) if f"{name}-hi-95" in out.columns else np.full(h, np.nan)
    lo80 = pd.to_numeric(out.get(f"{name}-lo-80", np.nan), errors="coerce").to_numpy(dtype=float) if f"{name}-lo-80" in out.columns else np.full(h, np.nan)
    hi80 = pd.to_numeric(out.get(f"{name}-hi-80", np.nan), errors="coerce").to_numpy(dtype=float) if f"{name}-hi-80" in out.columns else np.full(h, np.nan)
    return {
        "yhat": yhat,
        "lo95": lo95,
        "hi95": hi95,
        "lo80": lo80,
        "hi80": hi80,
    }


def rolling_origin_evaluate(
    data: pl.DataFrame,
    horizon: int = 1,
    n_folds: int = 3,
    min_train_size: int = MIN_PERIODS,
    frequency: str = "D",
    season_length: int | None = None,
    models: tuple[str, ...] = CANDIDATE_MODELS,
    time_col: str = "ds",
    value_col: str = "y",
) -> dict:
    """Temporal rolling-origin evaluation preserving fold training scale, interval validation,
    quantile loss, and relative MAE comparison against selected baseline.
    """
    df = _as_frame(data, time_col, value_col)
    n = df.height

    max_folds = max(1, (n - min_train_size) // horizon)
    actual_folds = min(n_folds, max_folds)
    if actual_folds < 1 or n < min_train_size + horizon:
        raise ForecastRefused(
            f"rolling origin evaluation requires at least {min_train_size + horizon} periods for horizon {horizon}; found {n}",
            missing=[f"{min_train_size + horizon - n} more periods"],
            actions=["increase series history or reduce horizon/min_train_size"],
        )

    m = _effective_season(season_length, frequency, min_train_size)

    model_fold_results: dict[str, list[dict]] = {name: [] for name in models}

    for fold_idx in range(actual_folds):
        train_end = n - (actual_folds - fold_idx) * horizon
        train_df = df.head(train_end)
        test_df = df.slice(train_end, horizon)
        actual_y = test_df["y"].to_numpy()
        train_y = train_df["y"].to_numpy()

        for name in models:
            try:
                fit_res = _fit_predict_with_intervals(train_df, name, m, frequency, horizon)
                yhat = fit_res["yhat"]
                lo95 = fit_res["lo95"]
                hi95 = fit_res["hi95"]
                lo80 = fit_res["lo80"]
                hi80 = fit_res["hi80"]

                metrics = _metrics(actual_y, yhat, train_y, m)

                cov95 = float(np.mean((lo95 <= actual_y) & (actual_y <= hi95))) if not np.isnan(lo95).all() else None
                cov80 = float(np.mean((lo80 <= actual_y) & (actual_y <= hi80))) if not np.isnan(lo80).all() else None

                interval_val = validate_forecast_intervals(yhat, lo95, hi95, lo80, hi80)

                model_fold_results[name].append({
                    "fold": fold_idx,
                    "train_size": train_end,
                    "horizon": horizon,
                    "mae": metrics["mae"],
                    "mase": metrics["mase"],
                    "rmse": metrics["rmse"],
                    "mape": metrics["mape"],
                    "coverage_95": _r(cov95),
                    "coverage_80": _r(cov80),
                    "valid_nesting": interval_val["valid_nesting"],
                    "valid_bounds": interval_val["valid_bounds"],
                    "quantile_loss": {
                        "q025": pinball_loss(actual_y, lo95, 0.025),
                        "q10": pinball_loss(actual_y, lo80, 0.10),
                        "q90": pinball_loss(actual_y, hi80, 0.90),
                        "q975": pinball_loss(actual_y, hi95, 0.975),
                    },
                })
            except Exception as e:  # noqa: BLE001 - any candidate failure is recorded as a fold error, not fatal
                model_fold_results[name].append({
                    "fold": fold_idx,
                    "train_size": train_end,
                    "horizon": horizon,
                    "error": str(e),
                })

    aggregated_comparisons = []
    baseline_maes: dict[str, float] = {}

    for b_name in BASELINE_MODELS:
        folds = [f for f in model_fold_results.get(b_name, []) if "mae" in f and f["mae"] is not None]
        if folds:
            baseline_maes[b_name] = float(np.mean([f["mae"] for f in folds]))

    ref_baseline_name = "Naive" if "Naive" in baseline_maes else (next(iter(baseline_maes.keys())) if baseline_maes else None)
    ref_baseline_mae = baseline_maes.get(ref_baseline_name) if ref_baseline_name else None

    for name in models:
        folds = [f for f in model_fold_results[name] if "mae" in f and f["mae"] is not None]
        if not folds:
            aggregated_comparisons.append({
                "model_name": name,
                "mae": None,
                "mase": None,
                "rmse": None,
                "mape": None,
                "relative_mae": None,
                "empirical_coverage_95": None,
                "empirical_coverage_80": None,
                "error": "fit_failed",
            })
            continue

        mean_mae = float(np.mean([f["mae"] for f in folds]))
        mases = [f["mase"] for f in folds if f["mase"] is not None]
        mean_mase = float(np.mean(mases)) if mases else None
        rmses = [f["rmse"] for f in folds if f["rmse"] is not None]
        mean_rmse = float(np.mean(rmses)) if rmses else None
        mapes = [f["mape"] for f in folds if f["mape"] is not None]
        mean_mape = float(np.mean(mapes)) if mapes else None

        cov95s = [f["coverage_95"] for f in folds if f["coverage_95"] is not None]
        mean_cov95 = float(np.mean(cov95s)) if cov95s else None

        cov80s = [f["coverage_80"] for f in folds if f["coverage_80"] is not None]
        mean_cov80 = float(np.mean(cov80s)) if cov80s else None

        rel_mae = (mean_mae / ref_baseline_mae) if (ref_baseline_mae and ref_baseline_mae > 0) else 1.0

        aggregated_comparisons.append({
            "model_name": name,
            "mae": _r(mean_mae),
            "mase": _r(mean_mase),
            "rmse": _r(mean_rmse),
            "mape": _r(mean_mape),
            "relative_mae": _r(rel_mae),
            "empirical_coverage_95": _r(mean_cov95),
            "empirical_coverage_80": _r(mean_cov80),
            "fold_count": len(folds),
            "error": None,
        })

    aggregated_comparisons.sort(key=lambda c: (c["mase"] is None, c["mase"] if c["mase"] is not None else 0.0))

    return {
        "comparisons": aggregated_comparisons,
        "fold_details": model_fold_results,
        "fold_count": actual_folds,
        "sample_size": n,
        "horizon": horizon,
        "season_length": m,
        "frequency": frequency,
        "baseline_model": ref_baseline_name,
    }


def evaluate(
    data: pl.DataFrame,
    test_size: float = 0.2,
    frequency: str = "D",
    season_length: int | None = None,
    models: tuple[str, ...] = CANDIDATE_MODELS,
    time_col: str = "ds",
    value_col: str = "y",
    use_rolling_origin: bool = False,
    n_folds: int = 3,
) -> dict:
    """Compare candidate models on a historical holdout (§16 workflow 3)."""
    if use_rolling_origin:
        return rolling_origin_evaluate(
            data=data,
            horizon=max(1, round(data.height * test_size)),
            n_folds=n_folds,
            min_train_size=MIN_PERIODS,
            frequency=frequency,
            season_length=season_length,
            models=models,
            time_col=time_col,
            value_col=value_col,
        )

    df = _as_frame(data, time_col, value_col)
    n = df.height
    if n < MIN_PERIODS:
        raise ForecastRefused(
            f"evaluation requires at least {MIN_PERIODS} periods; found {n}",
            missing=[f"{MIN_PERIODS - n} more periods of history"],
            actions=["upload more history or aggregate to a coarser frequency"],
        )
    holdout = max(3, min(round(n * test_size), n - MIN_PERIODS))
    train, test = df.head(n - holdout), df.tail(holdout)
    m = _effective_season(season_length, frequency, train.height)

    comparisons = []
    baseline_maes: dict[str, float] = {}

    for name in models:
        try:
            pred = _fit_predict(train, name, m, frequency, holdout)
        except Exception:  # noqa: BLE001 - a candidate failing to converge is reported, not fatal
            comparisons.append({"model_name": name, "mae": None, "mape": None, "mase": None, "rmse": None, "relative_mae": None, "error": "fit_failed"})
            continue
        res = _metrics(test["y"].to_numpy(), pred, train["y"].to_numpy(), m)
        if name in BASELINE_MODELS and res["mae"] is not None:
            baseline_maes[name] = res["mae"]
        comparisons.append({"model_name": name, "error": None, **res})

    ref_baseline = baseline_maes.get("Naive") or (next(iter(baseline_maes.values())) if baseline_maes else None)
    for c in comparisons:
        if c.get("mae") is not None and ref_baseline and ref_baseline > 0:
            c["relative_mae"] = _r(c["mae"] / ref_baseline)

    comparisons.sort(key=lambda c: (c["mase"] is None, c["mase"] if c["mase"] is not None else 0.0))
    return {
        "comparisons": comparisons,
        "holdout_size": holdout,
        "train_size": train.height,
        "season_length": m,
        "frequency": frequency,
        "baseline_model": _baseline_winner(comparisons),
    }


def capture_forecast_evidence(
    store: Store,
    tenant_id: str,
    user_id: str,
    investigation_id: str,
    metric_id: str,
    dataset_id: str,
    dataset_revision: int,
    model_spec: dict,
    eval_metrics: dict,
    forecast_df: pl.DataFrame,
    support_status: str = "supporting",
) -> dict:
    """Capture forecast evaluation and predictions as an immutable D2 evidence artifact (evidence_type = 'estimated')."""
    inv = store.conn.execute(
        "SELECT id FROM investigation WHERE tenant_id=? AND id=?",
        (tenant_id, investigation_id),
    ).fetchone()
    if inv is None:
        raise ForecastRefused("investigation_not_found", actions=["create investigation before capturing forecast evidence"])

    rows = forecast_df.to_dicts()
    digest_payload = {
        "metric_id": metric_id,
        "dataset_id": dataset_id,
        "dataset_revision": dataset_revision,
        "model_name": model_spec.get("model_name"),
        "params": model_spec.get("params"),
        "eval_metrics": eval_metrics,
        "forecast_rows": rows,
    }

    digest = compute_canonical_digest(digest_payload)
    artifact_id = f"ev-{new_id()[:12]}"
    created_at = now_iso()

    quality_flags = ["estimated_forecast"]
    if eval_metrics.get("mase") is None:
        quality_flags.append("undefined_mase_scale")

    payload_json = json.dumps({
        "model_spec": model_spec,
        "evaluation_metrics": eval_metrics,
        "forecast": rows,
    })

    store.conn.execute(
        """INSERT INTO evidence_artifact(
            tenant_id, id, investigation_id, parent_artifact_ids_json, evidence_type, support_status,
            quality_flags_json, metric_id, definition_version, dataset_id, dataset_revision,
            resolved_plan_json, query_params_json, canonical_digest, storage_format, payload_json,
            parquet_key, row_count, exactness_class, reproducibility_status, created_by, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            tenant_id,
            artifact_id,
            investigation_id,
            json.dumps([]),
            "estimated",
            support_status,
            json.dumps(quality_flags),
            metric_id,
            1,
            dataset_id,
            dataset_revision,
            json.dumps({"type": "forecast", "model": model_spec.get("model_name")}),
            json.dumps({"horizon": model_spec.get("horizon")}),
            digest,
            "json",
            payload_json,
            None,
            len(rows),
            "stochastically_reproducible",
            "reproducible",
            user_id,
            created_at,
        ),
    )
    store.conn.commit()

    return {
        "artifact_id": artifact_id,
        "evidence_type": "estimated",
        "digest": digest,
        "created_at": created_at,
    }


def _baseline_winner(comparisons: list[dict]) -> str | None:
    best = None
    for c in comparisons:
        if c["model_name"] in BASELINE_MODELS and c["mase"] is not None and (best is None or c["mase"] < best["mase"]):
            best = c
    return best["model_name"] if best else None


def _effective_season(season_length: int | None, frequency: str, n_train: int) -> int:
    m = int(season_length) if season_length else DEFAULT_SEASON[frequency]
    return max(1, min(m, max(1, n_train // 2)))


def train_model(
    data: pl.DataFrame,
    metric_config: dict,
    horizon: int,
    time_col: str = "ds",
    value_col: str = "y",
) -> dict:
    """Fit candidates on a holdout, keep the simplest model that wins, then
    refit on all history. Returns a JSON-safe model_spec (§16 workflow 2–4)."""
    if horizon < 1 or horizon > 365:
        raise ForecastRefused("horizon must be between 1 and 365 periods")
    frequency = metric_config.get("frequency", "D")
    if frequency not in FREQ_TRUNCATE:
        raise ForecastRefused(f"unsupported frequency {frequency}", actions=[f"use one of {sorted(FREQ_TRUNCATE)}"])
    season_length = metric_config.get("season_length") or DEFAULT_SEASON[frequency]

    df = _as_frame(data, time_col, value_col)
    suitability = check_suitability(df, min_periods=MIN_PERIODS)
    if not suitability["sufficient"]:
        raise ForecastRefused(suitability["reason"], missing=[f"{MIN_PERIODS - suitability['observations']} more periods"], actions=suitability["recommended_actions"])

    ev = evaluate(df, frequency=frequency, season_length=season_length)
    m = ev["season_length"]
    winner = _select(ev["comparisons"], m)

    # refit probe on the full history: fail at train time, not at predict time
    _fit_predict(df, winner, m, frequency, 1)
    spec = {
        "model_name": winner,
        "params": {"season_length": m, "frequency": frequency},
        "training_end": df["ds"].max().isoformat(),
        "training_points": df.height,
        "horizon": horizon,
        "evaluation_metrics": _winner_metrics(ev["comparisons"], winner),
        "holdout_size": ev["holdout_size"],
        "comparisons": ev["comparisons"],
        "baseline_model": ev["baseline_model"],
        "assumptions": ASSUMPTIONS,
        "limitations": LIMITATIONS,
        "series": [[d.isoformat(), y] for d, y in zip(df["ds"].to_list(), df["y"].to_list())],
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    return spec


def _select(comparisons: list[dict], m: int) -> str:
    """Complex models must earn their place (§16 principle 2)."""
    scored = [c for c in comparisons if c.get("mase") is not None]
    if not scored:
        raise ForecastRefused("no candidate model produced a valid evaluation", actions=["check data quality and try a coarser frequency"])
    best = min(scored, key=lambda c: c["mase"])
    baseline_name = _baseline_winner(comparisons)
    baseline = next((c for c in scored if c["model_name"] == baseline_name), None)
    if (
        baseline is not None
        and best["model_name"] not in BASELINE_MODELS
        and COMPLEXITY[best["model_name"]] > COMPLEXITY[baseline["model_name"]]
        and (baseline["mase"] - best["mase"]) / baseline["mase"] <= COMPLEXITY_MARGIN
    ):
        return baseline["model_name"]  # complex model did not earn its place
    return best["model_name"]


def _winner_metrics(comparisons: list[dict], winner: str) -> dict:
    c = next((x for x in comparisons if x["model_name"] == winner), {})
    return {"mape": c.get("mape"), "mase": c.get("mase"), "rmse": c.get("rmse")}


# --------------------------------------------------------------------------
# prediction
# --------------------------------------------------------------------------

def predict(
    model_spec: dict,
    horizon: int | None = None,
    prediction_intervals: bool = True,
    level: list[int] | None = None,
) -> pl.DataFrame:
    """Refit the spec's model on its stored series and forecast `horizon`
    periods ahead with 80%/95% intervals (§16 workflow 4)."""
    h = int(horizon if horizon is not None else model_spec.get("horizon", 0))
    if h < 1 or h > 365:
        raise ForecastRefused("horizon must be between 1 and 365 periods")
    name = model_spec["model_name"]
    params = model_spec["params"]
    m = params["season_length"]
    frequency = params["frequency"]
    series = pl.DataFrame(
        {"ds": [pd.Timestamp(d) for d, _ in model_spec["series"]], "y": [y for _, y in model_spec["series"]]},
        schema={"ds": pl.Datetime("us"), "y": pl.Float64},
    )
    if series.height < MIN_PERIODS:
        raise ForecastRefused(f"stored series has only {series.height} periods; minimum {MIN_PERIODS}")

    sf = StatsForecast([_make_model(name, m)], freq=FREQ_PANDAS[frequency], n_jobs=1)
    sf.fit(_to_pandas(series))
    levels = level if prediction_intervals and level is not None else ([80, 95] if prediction_intervals else None)
    out = sf.predict(h=h, level=levels) if levels else sf.predict(h=h)

    yhat = pd.to_numeric(out[name], errors="coerce").to_numpy(dtype=float)
    lo = pd.to_numeric(out[f"{name}-lo-95"], errors="coerce").to_numpy(dtype=float) if prediction_intervals else np.full(h, np.nan)
    hi = pd.to_numeric(out[f"{name}-hi-95"], errors="coerce").to_numpy(dtype=float) if prediction_intervals else np.full(h, np.nan)
    lo80 = pd.to_numeric(out[f"{name}-lo-80"], errors="coerce").to_numpy(dtype=float) if prediction_intervals else np.full(h, np.nan)
    hi80 = pd.to_numeric(out[f"{name}-hi-80"], errors="coerce").to_numpy(dtype=float) if prediction_intervals else np.full(h, np.nan)

    def _f(a):
        return [None if not math.isfinite(v) else round(float(v), 6) for v in a]

    return pl.DataFrame(
        {
            "ds": [d.isoformat() for d in pd.to_datetime(out["ds"])],
            "yhat": _f(yhat),
            "yhat_lower": _f(lo),
            "yhat_upper": _f(hi),
            "yhat_lower_80": _f(lo80),
            "yhat_upper_80": _f(hi80),
        }
    )
