"""M2 Forecasting Lab tests (spec §16): suitability refusal on thin history,
baseline-first model selection, holdout metrics, prediction intervals, and the
API surface end-to-end against the fixture dataset."""

from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl
import pytest

from conftest import FIXTURES, upload_and_finalize
from decisionos_analytics.forecasting import (
    CANDIDATE_MODELS,
    ForecastRefused,
    build_metric_series,
    check_suitability,
    evaluate,
    predict,
    train_model,
)
from decisionos_analytics.semantics import MetricDefinitionContent


def seasonal_series(n: int = 60, seed: int = 3) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    y = 100 + 0.8 * t + 8 * np.sin(t * 2 * np.pi / 7) + rng.normal(0, 4, n)
    return pl.DataFrame({"ds": pd.date_range("2026-01-01", periods=n, freq="D"), "y": y})


# ---- suitability ------------------------------------------------------------

def test_check_suitability_refuses_short_history():
    suit = check_suitability(seasonal_series(5))
    assert suit["sufficient"] is False
    assert "12" in suit["reason"]  # names the minimum
    assert suit["recommended_actions"]  # tells the user what data is needed


def test_check_suitability_accepts_long_history_and_flags_constant():
    ok = check_suitability(seasonal_series(40))
    assert ok["sufficient"] is True
    assert ok["observations"] == 40
    flat = pl.DataFrame({"ds": pd.date_range("2026-01-01", periods=30, freq="D"), "y": [5.0] * 30})
    warn = check_suitability(flat)
    assert warn["sufficient"] is True  # forecastable, but...
    assert any("constant" in w for w in warn["warnings"])  # ...explicitly flagged


# ---- evaluation ---------------------------------------------------------------

def test_evaluate_refuses_below_min_periods():
    with pytest.raises(ForecastRefused) as exc:
        evaluate(seasonal_series(8))
    assert "12 periods" in exc.value.reason


def test_evaluate_returns_metrics_for_all_candidates():
    ev = evaluate(seasonal_series(48))
    names = {c["model_name"] for c in ev["comparisons"]}
    assert names == set(CANDIDATE_MODELS)
    scored = [c for c in ev["comparisons"] if c["mase"] is not None]
    assert len(scored) >= 3  # baselines always score
    assert scored == sorted(scored, key=lambda c: c["mase"])  # sorted best-first
    for c in scored:
        assert c["rmse"] is not None and c["rmse"] >= 0
        assert c["mape"] is not None and c["mape"] >= 0


# ---- training -----------------------------------------------------------------

def test_train_model_returns_spec_with_evaluation_and_caveats():
    spec = train_model(seasonal_series(48), {"frequency": "D"}, 7)
    assert spec["model_name"] in CANDIDATE_MODELS
    assert spec["params"]["frequency"] == "D"
    assert spec["training_end"].startswith("2026-02")  # last ds of the 48-day series
    assert spec["training_points"] == 48
    assert spec["evaluation_metrics"]["mase"] is not None
    assert spec["assumptions"] and spec["limitations"]  # §16 principle 3
    # complex models must earn their place: winner is no worse than the baseline
    winner = next(c for c in spec["comparisons"] if c["model_name"] == spec["model_name"])
    baseline = next(c for c in spec["comparisons"] if c["model_name"] == spec["baseline_model"])
    assert winner["mase"] <= baseline["mase"] + 1e-9


def test_train_model_refuses_insufficient_history():
    with pytest.raises(ForecastRefused):
        train_model(seasonal_series(6), {"frequency": "D"}, 7)


# ---- prediction ---------------------------------------------------------------

def test_predict_returns_horizon_rows_with_intervals():
    spec = train_model(seasonal_series(48), {"frequency": "D"}, 7)
    preds = predict(spec)
    assert preds.height == 7
    assert set(preds.columns) >= {"ds", "yhat", "yhat_lower", "yhat_upper"}
    assert preds["yhat"].null_count() == 0
    assert (preds["yhat_lower"] <= preds["yhat"]).all()
    assert (preds["yhat"] <= preds["yhat_upper"]).all()
    dss = [pd.Timestamp(d) for d in preds["ds"].to_list()]
    assert dss == sorted(dss)
    assert (dss[0] - pd.Timestamp(spec["training_end"])).days == 1  # starts right after training


def test_predict_without_intervals_nulls_bounds():
    spec = train_model(seasonal_series(48), {"frequency": "D"}, 5)
    preds = predict(spec, prediction_intervals=False)
    assert preds.height == 5
    assert preds["yhat_lower"].null_count() == 5
    assert preds["yhat_upper"].null_count() == 5


# ---- series building ------------------------------------------------------------

VOL_DEF = {
    "metric_id": "metric-ticket-volume",
    "name": "Daily ticket volume",
    "kind": "count",
    "expression": {"kind": "count", "predicates": []},
    "eligibility": [],
    "time_basis": "created_at",
    "timezone": "Asia/Bahrain",
    "dataset_id": "ds-1",
}


def test_build_metric_series_buckets_counts_per_day():
    frame = pl.read_csv(FIXTURES / "tenant_alpha" / "tickets_cases.csv")
    series = build_metric_series(frame, MetricDefinitionContent.model_validate(VOL_DEF), frequency="D")
    assert series.columns == ["ds", "y"]
    assert series.height == 90  # one bucket per day in the fixture window
    assert series["y"].sum() == frame.height


# ---- API surface ---------------------------------------------------------------

def _publish_volume_metric(client, alpha_headers, modeler_headers):
    uid, fin = upload_and_finalize(client, alpha_headers, FIXTURES / "tenant_alpha" / "tickets_cases.csv")
    dataset_id = fin["dataset_id"]
    client.post(f"/v1/datasets/{dataset_id}/grain-confirmation", json={"key_columns": ["case_id"]}, headers=alpha_headers)
    client.post(f"/v1/datasets/{dataset_id}/revisions/{fin['revision']}/publish", headers=alpha_headers)
    r = client.post("/v1/metrics/definitions", json=VOL_DEF | {"dataset_id": dataset_id}, headers=modeler_headers)
    version = r.json()["version"]
    client.post(f"/v1/metrics/definitions/{VOL_DEF['metric_id']}/approve", json={"version": version, "change_reason": "reviewed"}, headers=alpha_headers)
    return dataset_id


def test_forecast_api_requires_certified_metric(client, alpha_headers, modeler_headers):
    uid, fin = upload_and_finalize(client, alpha_headers, FIXTURES / "tenant_alpha" / "tickets_cases.csv")
    dataset_id = fin["dataset_id"]
    client.post(f"/v1/datasets/{dataset_id}/grain-confirmation", json={"key_columns": ["case_id"]}, headers=alpha_headers)
    client.post(f"/v1/datasets/{dataset_id}/revisions/{fin['revision']}/publish", headers=alpha_headers)
    # proposed but never approved -> not certified -> suitability refuses
    client.post("/v1/metrics/definitions", json=VOL_DEF | {"dataset_id": dataset_id}, headers=modeler_headers)
    r = client.post("/v1/forecasts/suitability", json={"dataset_id": dataset_id, "metric_id": VOL_DEF["metric_id"]}, headers=alpha_headers)
    assert r.status_code == 200  # refusal is an answer, not an error
    body = r.json()
    assert body["sufficient"] is False
    assert body["reason"] == "insufficient_data"
    assert "approved definition version" in body["missing_requirements"]


def test_forecast_api_full_flow(client, alpha_headers, modeler_headers):
    dataset_id = _publish_volume_metric(client, alpha_headers, modeler_headers)
    metric_id = VOL_DEF["metric_id"]

    r = client.post("/v1/forecasts/suitability", json={"dataset_id": dataset_id, "metric_id": metric_id, "time_basis": "created_at"}, headers=alpha_headers)
    suit = r.json()
    assert suit["sufficient"] is True and suit["observations"] == 90

    r = client.post("/v1/forecasts/evaluate", json={"dataset_id": dataset_id, "metric_id": metric_id, "test_size": 0.2}, headers=alpha_headers)
    ev = r.json()
    assert ev["status"] == "answered"
    assert {c["model_name"] for c in ev["comparisons"]} == set(CANDIDATE_MODELS)

    r = client.post("/v1/forecasts/train", json={"dataset_id": dataset_id, "metric_id": metric_id, "time_basis": "created_at", "horizon": 7, "frequency": "D", "season_length": 7}, headers=alpha_headers)
    assert r.status_code == 201
    trained = r.json()
    assert trained["status"] == "trained"
    assert trained["model_spec_id"]
    assert trained["evaluation"]["metrics"]["mase"] is not None
    assert trained["suitability"]["sufficient"] is True
    assert trained["assumptions"] and trained["limitations"]

    r = client.post("/v1/forecasts/predict", json={"model_spec_id": trained["model_spec_id"], "horizon": 7, "prediction_intervals": True}, headers=alpha_headers)
    pr = r.json()
    assert pr["status"] == "answered"
    assert len(pr["predictions"]) == 7
    first = pr["predictions"][0]
    assert first["yhat_lower"] <= first["yhat"] <= first["yhat_upper"]
    assert pr["evidence_ref"].startswith("evidence-")
    assert pr["model_info"]["model_name"] == trained["model_name"]


def test_forecast_model_spec_is_tenant_scoped(client, alpha_headers, modeler_headers, beta_headers):
    dataset_id = _publish_volume_metric(client, alpha_headers, modeler_headers)
    r = client.post("/v1/forecasts/train", json={"dataset_id": dataset_id, "metric_id": VOL_DEF["metric_id"], "horizon": 5, "frequency": "D"}, headers=alpha_headers)
    spec_id = r.json()["model_spec_id"]
    # QA-025: other tenants get 404, never an existence disclosure
    assert client.post("/v1/forecasts/predict", json={"model_spec_id": spec_id}, headers=beta_headers).status_code == 404
    # beta cannot see alpha's dataset: train refuses with insufficient_data, no disclosure
    r = client.post("/v1/forecasts/train", json={"dataset_id": dataset_id, "metric_id": VOL_DEF["metric_id"], "horizon": 5}, headers=beta_headers)
    assert r.json()["status"] == "insufficient_data"
