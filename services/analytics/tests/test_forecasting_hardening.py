"""WP-01 Forecasting Validation Hardening Unit Tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl
import pytest

from decisionos_analytics.forecasting import (
    BASELINE_MODELS,
    CANDIDATE_MODELS,
    ForecastRefused,
    capture_forecast_evidence,
    evaluate,
    predict,
    rolling_origin_evaluate,
    train_model,
    validate_forecast_intervals,
)
from decisionos_analytics.store import Store, new_id, now_iso


def sample_series(n: int = 40, constant: bool = False, seed: int = 42) -> pl.DataFrame:
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    if constant:
        return pl.DataFrame({"ds": dates, "y": [50.0] * n})
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    y = 50.0 + 0.5 * t + 5.0 * np.sin(2 * np.pi * t / 7) + rng.normal(0, 1.0, size=n)
    return pl.DataFrame({"ds": dates, "y": y})


def test_mase_zero_denominator_handled():
    """Verify constant series produces scale=0 and MASE=None (undefined)."""
    df = sample_series(30, constant=True)
    res = evaluate(df)
    for comp in res["comparisons"]:
        assert comp["mase"] is None, f"MASE should be None for constant series, got {comp['mase']}"


def test_rolling_origin_evaluation():
    """Test rolling-origin evaluation temporal folds and metrics."""
    df = sample_series(50, constant=False)
    res = rolling_origin_evaluate(
        data=df,
        horizon=3,
        n_folds=3,
        min_train_size=20,
        frequency="D",
    )
    assert res["fold_count"] == 3
    assert len(res["comparisons"]) == len(CANDIDATE_MODELS)
    assert res["baseline_model"] in BASELINE_MODELS

    for c in res["comparisons"]:
        if c["error"] is None:
            assert c["mae"] is not None and c["mae"] >= 0
            assert c["relative_mae"] is not None and c["relative_mae"] > 0
            assert c["fold_count"] == 3


def test_interval_validation_and_nesting():
    """Test lower <= point <= upper and quantile nesting."""
    yhat = np.array([10.0, 12.0, 15.0])
    lo95 = np.array([5.0, 6.0, 8.0])
    hi95 = np.array([15.0, 18.0, 22.0])
    lo80 = np.array([7.0, 8.0, 10.0])
    hi80 = np.array([13.0, 15.0, 18.0])

    val = validate_forecast_intervals(yhat, lo95, hi95, lo80, hi80)
    assert val["valid"] is True
    assert val["valid_bounds"] is True
    assert val["valid_nesting"] is True

    # Invert nesting: lo80 < lo95 (invalid)
    bad_lo80 = np.array([4.0, 8.0, 10.0])
    bad_val = validate_forecast_intervals(yhat, lo95, hi95, bad_lo80, hi80)
    assert bad_val["valid_nesting"] is False
    assert bad_val["valid"] is False


def test_capture_forecast_evidence_d2_integration(tmp_path):
    """Test capturing forecast evidence as D2 evidence artifact with evidence_type='estimated'."""
    store = Store(tmp_path / "control.sqlite3")
    tenant_id = "tenant_alpha"
    user_id = "alpha.manager"
    inv_id = f"inv-{new_id()[:8]}"

    # Insert investigation
    store.conn.execute(
        """INSERT INTO investigation (tenant_id, id, title, question, source_type, owner, created_by, created_at, updated_at)
        VALUES (?, ?, 'Forecast Check', 'Future trend?', 'ad_hoc', ?, ?, ?, ?)""",
        (tenant_id, inv_id, user_id, user_id, now_iso(), now_iso()),
    )
    store.conn.commit()

    df = sample_series(30)
    spec = train_model(df, {"frequency": "D"}, 5)
    preds = predict(spec, horizon=5)

    ev_record = capture_forecast_evidence(
        store=store,
        tenant_id=tenant_id,
        user_id=user_id,
        investigation_id=inv_id,
        metric_id="ticket_volume",
        dataset_id="ds-support",
        dataset_revision=1,
        model_spec=spec,
        eval_metrics=spec["evaluation_metrics"],
        forecast_df=preds,
    )

    assert ev_record["artifact_id"].startswith("ev-")
    assert ev_record["evidence_type"] == "estimated"

    # Query database to verify persistence and type
    row = store.conn.execute(
        "SELECT evidence_type, quality_flags_json, canonical_digest FROM evidence_artifact WHERE tenant_id=? AND id=?",
        (tenant_id, ev_record["artifact_id"]),
    ).fetchone()
    assert row is not None
    assert row["evidence_type"] == "estimated"
    assert "estimated_forecast" in row["quality_flags_json"]
