"""WP-06 Golden Corpus, E2E Operational Loop, Tenant Security & Release Certification."""

from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl
import pytest
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app
from decisionos_analytics.forecasting import (
    evaluate,
    predict,
    rolling_origin_evaluate,
    train_model,
    validate_forecast_intervals,
)
from decisionos_analytics.predictive import (
    FeatureContract,
    ModelStatus,
    RiskTargetSpec,
    create_predictive_target,
    get_prediction,
    get_predictive_model,
    record_prediction,
    register_predictive_model,
    transition_model_status,
)
from decisionos_analytics.risk import (
    BaseRateClassifier,
    CaseState,
    LogisticRegressionClassifier,
    PlattCalibrator,
    assess_risk_suitability,
    calculate_classification_metrics,
    check_outcome_maturity,
    determine_operating_threshold,
    evaluate_case_state,
    extract_point_in_time_features,
    promote_risk_model,
)


@pytest.fixture
def cert_app(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        yield client, app.state.store


# ---------------------------------------------------------------------------
# 10.2 Golden Forecast Tests
# ---------------------------------------------------------------------------

def test_golden_forecast_suite():
    # 1. Constant series -> MASE scale 0 -> MASE = None
    flat_df = pl.DataFrame({"ds": pd.date_range("2026-01-01", periods=30, freq="D"), "y": [10.0] * 30})
    flat_eval = evaluate(flat_df)
    for c in flat_eval["comparisons"]:
        assert c["mase"] is None

    # 2. Seasonal series & Rolling Origin
    rng = np.random.default_rng(42)
    t = np.arange(60)
    y = 100.0 + 0.5 * t + 10.0 * np.sin(2 * np.pi * t / 7) + rng.normal(0, 1.0, 60)
    seas_df = pl.DataFrame({"ds": pd.date_range("2026-01-01", periods=60, freq="D"), "y": y})

    ro_res = rolling_origin_evaluate(seas_df, horizon=3, n_folds=3, min_train_size=20)
    assert ro_res["fold_count"] == 3
    assert len(ro_res["comparisons"]) >= 3

    # 3. Interval ordering and coverage
    spec = train_model(seas_df, {"frequency": "D"}, 7)
    preds = predict(spec)
    val = validate_forecast_intervals(
        preds["yhat"].to_numpy(),
        preds["yhat_lower"].to_numpy(),
        preds["yhat_upper"].to_numpy(),
        preds["yhat_lower_80"].to_numpy(),
        preds["yhat_upper_80"].to_numpy(),
    )
    assert val["valid"] is True


# ---------------------------------------------------------------------------
# 10.3 Golden Classification Tests
# ---------------------------------------------------------------------------

def test_golden_classification_suite():
    # 1. Base rate
    y_true = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    br = BaseRateClassifier().fit(np.zeros((8, 2)), y_true)
    assert np.isclose(br.base_rate, 0.5)

    # 2. Perfectly separable data
    X_sep = np.array([[-2.0], [-1.5], [-1.0], [1.0], [1.5], [2.0]])
    y_sep = np.array([0, 0, 0, 1, 1, 1])
    lr_sep = LogisticRegressionClassifier().fit(X_sep, y_sep)
    probs_sep = lr_sep.predict_proba(X_sep)[:, 1]
    metrics_sep = calculate_classification_metrics(y_sep, probs_sep, threshold=0.5)
    assert metrics_sep["brier_score"] is not None and metrics_sep["brier_score"] < 0.10

    # 3. Leakage feature trap rejection
    fc = FeatureContract(feature_id="age")
    leak_df = pl.DataFrame({"case_id": ["c1"], "timestamp": ["2026-01-01T00:00:00Z"], "age": [5], "future_status": ["done"]})
    with pytest.raises(ValueError) as exc:
        extract_point_in_time_features(leak_df, "2026-01-01T00:00:00Z", [fc])
    assert "leakage trap column" in str(exc.value)

    # 4. Unmatured outcome
    matured, reason = check_outcome_maturity("2026-03-01T00:00:00Z", "7d", "2026-03-03T00:00:00Z", False)
    assert matured is False

    # 5. Capacity threshold selection
    probs = np.array([0.9, 0.8, 0.7, 0.6, 0.4, 0.3, 0.2, 0.1])
    th_res = determine_operating_threshold(probs, policy_type="capacity", policy_params={"capacity": 3})
    assert th_res["flagged_count"] == 3
    assert th_res["threshold"] == 0.7

    # 6. Already overdue case
    c_state, _ = evaluate_case_state("c100", "2026-03-05T00:00:00Z", "2026-03-04T00:00:00Z")
    assert c_state == CaseState.ALREADY_OVERDUE


# ---------------------------------------------------------------------------
# 10.4 Tenant Security Matrix Tests
# ---------------------------------------------------------------------------

def test_tenant_security_matrix(cert_app):
    client, store = cert_app
    alpha_mgr = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
    beta_mgr = {"X-Tenant": "tenant_beta", "X-User": "beta.manager"}

    # Target & Model created by Alpha
    tgt = client.post("/v1/predictive/targets", headers=alpha_mgr, json={"name": "Alpha Target", "outcome_definition": {"v": 1}, "outcome_window": "24h", "deadline_semantics": "fixed"}).json()
    mod = client.post("/v1/predictive/models", headers=alpha_mgr, json={"target_id": tgt["id"], "algorithm": "BaseRate", "training_time_range": ["a", "b"], "evaluation_time_range": ["c", "d"]}).json()

    # 1. tenant_alpha + alpha.manager -> Allowed
    assert client.get("/v1/predictive/targets", headers=alpha_mgr).status_code == 200
    assert client.get("/v1/predictive/models", headers=alpha_mgr).status_code == 200

    # 2. tenant_beta + alpha.manager -> 404 (mismatched user/tenant context)
    cross_hdr1 = {"X-Tenant": "tenant_beta", "X-User": "alpha.manager"}
    assert client.get("/v1/predictive/targets", headers=cross_hdr1).status_code == 404

    # 3. tenant_alpha + beta.manager -> 404
    cross_hdr2 = {"X-Tenant": "tenant_alpha", "X-User": "beta.manager"}
    assert client.get("/v1/predictive/targets", headers=cross_hdr2).status_code == 404

    # 4. Missing headers -> 401
    assert client.get("/v1/predictive/targets").status_code == 401

    # 5. Invalid user -> 401
    invalid_hdr = {"X-Tenant": "tenant_alpha", "X-User": "unknown.user"}
    assert client.get("/v1/predictive/targets", headers=invalid_hdr).status_code == 401

    # Verify zero DB side effects for denied score request
    row_count_before = store.conn.execute("SELECT count(*) as c FROM predictive_prediction").fetchone()["c"]
    client.post("/v1/predictive/score", headers=beta_mgr, json={"model_id": mod["id"], "case_id": "c999"})
    row_count_after = store.conn.execute("SELECT count(*) as c FROM predictive_prediction").fetchone()["c"]
    assert row_count_before == row_count_after


# ---------------------------------------------------------------------------
# 10.5 Historical Prediction Test
# ---------------------------------------------------------------------------

def test_historical_prediction_immutability(cert_app):
    client, store = cert_app
    alpha_mgr = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    tgt = create_predictive_target(store, "tenant_alpha", "T1", "workflow_case", {"v": 1}, "24h", "fixed", "alpha.manager")
    mod_v1 = register_predictive_model(store, "tenant_alpha", tgt["id"], "LogisticRegression", [], 1, {}, {}, {}, "platt", {}, {}, "chk1", "alpha.manager")
    transition_model_status(store, "tenant_alpha", mod_v1["id"], ModelStatus.EVALUATED, "alpha.manager")
    transition_model_status(store, "tenant_alpha", mod_v1["id"], ModelStatus.APPROVED, "alpha.manager")
    transition_model_status(store, "tenant_alpha", mod_v1["id"], ModelStatus.ACTIVE, "alpha.manager")

    p1 = record_prediction(
        store=store,
        tenant_id="tenant_alpha",
        model_id=mod_v1["id"],
        target_id=tgt["id"],
        entity_id="case-1",
        observation_time="2026-03-01T00:00:00Z",
        score=0.85,
        risk_tier="HIGH",
        threshold_used=0.50,
        outcome_window="24h",
        source_dataset_revision=1,
        feature_snapshot={"age": 10},
    )

    # Create Model V2
    mod_v2 = register_predictive_model(store, "tenant_alpha", tgt["id"], "LogisticRegression", [], 2, {}, {}, {}, "platt", {}, {}, "chk2", "alpha.manager")

    # Verify Prediction P1 remains pinned to Model V1 and unchanged
    saved_p1 = get_prediction(store, "tenant_alpha", p1["prediction_id"])
    assert saved_p1 is not None
    assert saved_p1["model_id"] == mod_v1["id"]
    assert saved_p1["model_version"] == 1
    assert saved_p1["score"] == 0.85


# ---------------------------------------------------------------------------
# 10.6 Evidence Integration & Decision Loop Test
# ---------------------------------------------------------------------------

def test_full_operational_decision_loop_integration(cert_app):
    client, store = cert_app
    alpha_mgr = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # 1. Create Risk Prediction
    tgt = client.post("/v1/predictive/targets", headers=alpha_mgr, json={"name": "SLA Target", "outcome_definition": {"v": 1}, "outcome_window": "24h", "deadline_semantics": "fixed"}).json()
    mod = client.post("/v1/predictive/models", headers=alpha_mgr, json={"target_id": tgt["id"], "algorithm": "BaseRate", "training_time_range": ["a", "b"], "evaluation_time_range": ["c", "d"]}).json()
    client.post(f"/v1/predictive/models/{mod['id']}/transition", headers=alpha_mgr, json={"status": "evaluated"})
    client.post(f"/v1/predictive/models/{mod['id']}/transition", headers=alpha_mgr, json={"status": "approved"})
    client.post(f"/v1/predictive/models/{mod['id']}/transition", headers=alpha_mgr, json={"status": "active"})

    score_res = client.post("/v1/predictive/score", headers=alpha_mgr, json={"model_id": mod["id"], "case_id": "CASE-100"}).json()

    # 2. Launch Investigation from Risk Prediction
    inv_res = client.post("/v1/investigations", headers=alpha_mgr, json={
        "title": "Risk Investigation CASE-100",
        "question": "What is driving breach risk?",
        "source_type": "predictive_risk",
        "source_id": "CASE-100"
    }).json()
    inv_id = inv_res.get("id") or inv_res.get("investigation_id")

    # 3. Bind Prediction to Evidence Artifact (type: estimated)
    ev_res = client.post(f"/v1/predictive/predictions/{score_res['prediction_id']}/evidence", headers=alpha_mgr, json={"investigation_id": inv_id}).json()
    assert ev_res["evidence_type"] == "estimated"

    # 4. Add Structured Claim to Investigation
    claim_res = client.post(f"/v1/investigations/{inv_id}/claims", headers=alpha_mgr, json={
        "statement": "Model predicts 65% chance of SLA breach due to queue depth",
        "evidence_type": "estimated",
        "support_status": "supporting",
        "evidence_id": ev_res["artifact_id"]
    }).json()
    assert claim_res["evidence_type"] == "estimated"

    # 5. Create Decision Brief from Investigation (explicit manual step)
    dec_res = client.post("/v1/decisions", headers=alpha_mgr, json={
        "title": "Add Support Capacity to Queue B",
        "brief": {
            "problem": "Elevated SLA breach risk on CASE-100",
            "relevant_findings": ["Risk score 0.85"],
            "proposed_action": "Reallocate 2 agents to Queue B",
            "baseline_option": "Do nothing",
            "scope": "Queue B",
            "owner": "alpha.manager",
            "trade_offs": [],
            "assumptions": [],
            "evidence_coverage": [ev_res["artifact_id"]],
            "validation_plan": "Monitor for 7 days",
            "counter_metrics": [],
            "expected_effect": "Reduce breach probability below 20%"
        }
    }).json()

    dec_id = dec_res.get("id") or dec_res.get("decision_id")
    assert dec_id is not None

    # Bind Evidence to Decision
    bind_res = client.post(f"/v1/decisions/{dec_id}/evidence", headers=alpha_mgr, json={
        "evidence_id": ev_res["artifact_id"],
        "binding_role": "primary_support"
    })
    assert bind_res.status_code == 201

    # Verify no automatic causal or decision promotion occurred
    dec_row = store.conn.execute("SELECT status FROM decision WHERE tenant_id=? AND id=?", ("tenant_alpha", dec_id)).fetchone()
    assert dec_row["status"] == "draft"  # Decision remains in draft state awaiting human review


# ---------------------------------------------------------------------------
# 10.7 Model Lifecycle Tests
# ---------------------------------------------------------------------------

def test_model_lifecycle_transitions_and_enforcement(cert_app):
    client, store = cert_app
    alpha_mgr = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    tgt = create_predictive_target(store, "tenant_alpha", "T_Life", "workflow_case", {"v": 1}, "24h", "fixed", "alpha.manager")
    mod = register_predictive_model(store, "tenant_alpha", tgt["id"], "BaseRate", [], 1, {}, {}, {}, "platt", {}, {}, "chk1", "alpha.manager")

    # 1. Valid transitions
    transition_model_status(store, "tenant_alpha", mod["id"], ModelStatus.EVALUATED, "alpha.manager")
    transition_model_status(store, "tenant_alpha", mod["id"], ModelStatus.APPROVED, "alpha.manager")
    transition_model_status(store, "tenant_alpha", mod["id"], ModelStatus.ACTIVE, "alpha.manager")

    # 2. Invalid reverse transition (active -> draft)
    with pytest.raises(ValueError):
        transition_model_status(store, "tenant_alpha", mod["id"], ModelStatus.DRAFT, "alpha.manager")

    # 3. Transition active -> suspended
    transition_model_status(store, "tenant_alpha", mod["id"], ModelStatus.SUSPENDED, "alpha.manager")

    # Suspended model cannot score
    with pytest.raises(ValueError) as exc:
        record_prediction(store, "tenant_alpha", mod["id"], tgt["id"], "c1", "2026-03-01T00:00:00Z", 0.5, "LOW", 0.5, "24h", 1, {})
    assert "SUSPENDED" in str(exc.value)

    # 4. Transition suspended -> retired
    transition_model_status(store, "tenant_alpha", mod["id"], ModelStatus.RETIRED, "alpha.manager")

    # Retired model remains available for historical reading
    ret_mod = get_predictive_model(store, "tenant_alpha", mod["id"])
    assert ret_mod is not None
    assert ret_mod["status"] == "retired"
