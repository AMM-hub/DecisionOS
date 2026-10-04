"""WP-04 Prediction Persistence & D2 Evidence Integration Tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app


@pytest.fixture
def api_client(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        yield client, app.state.store


def test_predictive_targets_api(api_client):
    client, store = api_client
    alpha_headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # 1. Create Target
    resp = client.post(
        "/v1/predictive/targets",
        headers=alpha_headers,
        json={
            "name": "Support Ticket SLA 24h",
            "entity_type": "workflow_case",
            "outcome_definition": {"metric": "duration", "operator": "gt", "value": 24.0},
            "outcome_window": "24h",
            "deadline_semantics": "fixed",
        }
    )
    assert resp.status_code == 201
    target = resp.json()
    assert target["id"].startswith("tgt-")
    assert target["name"] == "Support Ticket SLA 24h"

    # 2. List Targets
    list_resp = client.get("/v1/predictive/targets", headers=alpha_headers)
    assert list_resp.status_code == 200
    targets = list_resp.json()
    assert len(targets) == 1
    assert targets[0]["id"] == target["id"]


def test_predictive_models_and_transitions_api(api_client):
    client, _ = api_client
    alpha_headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # Target
    tgt_res = client.post(
        "/v1/predictive/targets",
        headers=alpha_headers,
        json={
            "name": "Case SLA Target",
            "outcome_definition": {"value": 1},
            "outcome_window": "24h",
            "deadline_semantics": "fixed",
        }
    ).json()

    # Register Model (Draft)
    mod_res = client.post(
        "/v1/predictive/models",
        headers=alpha_headers,
        json={
            "target_id": tgt_res["id"],
            "algorithm": "LogisticRegression",
            "feature_contract_specs": [{"feature_id": "case_age_hours"}],
            "training_time_range": ["2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"],
            "evaluation_time_range": ["2026-02-01T00:00:00Z", "2026-02-15T00:00:00Z"],
        }
    )
    assert mod_res.status_code == 201
    model = mod_res.json()
    assert model["status"] == "draft"

    # Valid Transition: draft -> evaluated
    t1 = client.post(
        f"/v1/predictive/models/{model['id']}/transition",
        headers=alpha_headers,
        json={"status": "evaluated"}
    )
    assert t1.status_code == 200
    assert t1.json()["status"] == "evaluated"

    # Valid Transition: evaluated -> approved
    t2 = client.post(
        f"/v1/predictive/models/{model['id']}/transition",
        headers=alpha_headers,
        json={"status": "approved"}
    )
    assert t2.status_code == 200

    # Valid Transition: approved -> active
    t3 = client.post(
        f"/v1/predictive/models/{model['id']}/transition",
        headers=alpha_headers,
        json={"status": "active"}
    )
    assert t3.status_code == 200
    assert t3.json()["status"] == "active"


def test_predictive_scoring_and_suspended_model(api_client):
    client, _ = api_client
    alpha_headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # Target & Active Model
    tgt = client.post("/v1/predictive/targets", headers=alpha_headers, json={"name": "T1", "outcome_definition": {"v": 1}, "outcome_window": "24h", "deadline_semantics": "fixed"}).json()
    mod = client.post("/v1/predictive/models", headers=alpha_headers, json={"target_id": tgt["id"], "algorithm": "BaseRate", "feature_contract_specs": [], "training_time_range": ["a", "b"], "evaluation_time_range": ["c", "d"]}).json()
    
    # Activate model
    client.post(f"/v1/predictive/models/{mod['id']}/transition", headers=alpha_headers, json={"status": "evaluated"})
    client.post(f"/v1/predictive/models/{mod['id']}/transition", headers=alpha_headers, json={"status": "approved"})
    client.post(f"/v1/predictive/models/{mod['id']}/transition", headers=alpha_headers, json={"status": "active"})

    # 1. Score eligible case
    score_res = client.post(
        "/v1/predictive/score",
        headers=alpha_headers,
        json={
            "model_id": mod["id"],
            "case_id": "case-999",
            "observation_time": "2026-03-01T10:00:00Z",
            "deadline": "2026-03-02T10:00:00Z",
        }
    )
    assert score_res.status_code == 200
    res = score_res.json()
    assert res["case_state"] == "eligible"
    assert res["score"] is not None
    assert res["prediction_id"].startswith("prd-")

    # 2. Score already overdue case -> returns state already_overdue and score None
    overdue_res = client.post(
        "/v1/predictive/score",
        headers=alpha_headers,
        json={
            "model_id": mod["id"],
            "case_id": "case-888",
            "observation_time": "2026-03-03T10:00:00Z",
            "deadline": "2026-03-02T10:00:00Z",  # Deadline in past relative to obs time
        }
    ).json()
    assert overdue_res["case_state"] == "already_overdue"
    assert overdue_res["score"] is None

    # 3. Suspend model -> score attempt returns prediction_unavailable
    client.post(f"/v1/predictive/models/{mod['id']}/transition", headers=alpha_headers, json={"status": "suspended"})
    susp_res = client.post("/v1/predictive/score", headers=alpha_headers, json={"model_id": mod["id"], "case_id": "case-777"}).json()
    assert susp_res["case_state"] == "prediction_unavailable"
    assert susp_res["score"] is None


def test_prediction_evidence_and_tenant_isolation_404(api_client):
    client, store = api_client
    alpha_headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
    beta_headers = {"X-Tenant": "tenant_beta", "X-User": "beta.manager"}

    # Target & Active Model for Alpha
    tgt = client.post("/v1/predictive/targets", headers=alpha_headers, json={"name": "T_Alpha", "outcome_definition": {"v": 1}, "outcome_window": "24h", "deadline_semantics": "fixed"}).json()
    mod = client.post("/v1/predictive/models", headers=alpha_headers, json={"target_id": tgt["id"], "algorithm": "BaseRate", "feature_contract_specs": [], "training_time_range": ["a", "b"], "evaluation_time_range": ["c", "d"]}).json()
    client.post(f"/v1/predictive/models/{mod['id']}/transition", headers=alpha_headers, json={"status": "evaluated"})
    client.post(f"/v1/predictive/models/{mod['id']}/transition", headers=alpha_headers, json={"status": "approved"})
    client.post(f"/v1/predictive/models/{mod['id']}/transition", headers=alpha_headers, json={"status": "active"})

    score_res = client.post("/v1/predictive/score", headers=alpha_headers, json={"model_id": mod["id"], "case_id": "case-alpha"}).json()
    pred_id = score_res["prediction_id"]

    # Alpha investigation
    inv_res = client.post("/v1/investigations", headers=alpha_headers, json={"title": "Alpha Risk Inv", "question": "Why?"}).json()
    inv_id = inv_res["id"]

    # Bind prediction to evidence
    ev_res = client.post(
        f"/v1/predictive/predictions/{pred_id}/evidence",
        headers=alpha_headers,
        json={"investigation_id": inv_id}
    )
    assert ev_res.status_code == 201
    ev = ev_res.json()
    assert ev["evidence_type"] == "estimated"
    assert ev["artifact_id"].startswith("ev-")

    # SECURITY TENANT ISOLATION TESTS
    # Tenant Beta attempts to access Tenant Alpha's prediction -> 404 Not Found
    b_pred = client.get(f"/v1/predictive/predictions/{pred_id}", headers=beta_headers)
    assert b_pred.status_code == 404

    # Tenant Beta attempts to score Tenant Alpha's model -> 404 Not Found
    b_score = client.post("/v1/predictive/score", headers=beta_headers, json={"model_id": mod["id"], "case_id": "case-cross"})
    assert b_score.status_code == 404

    # Tenant Beta attempts to capture evidence on Tenant Alpha's prediction -> 404 Not Found
    b_ev = client.post(f"/v1/predictive/predictions/{pred_id}/evidence", headers=beta_headers, json={"investigation_id": inv_id})
    assert b_ev.status_code == 404
