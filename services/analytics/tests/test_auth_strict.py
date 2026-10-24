"""Comprehensive Strict Authentication and Tenant Isolation Tests (R2 / SEC-01)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app
from decisionos_analytics.security import (
    ROLE_PERMISSIONS,
    create_access_token,
    has_permission,
    verify_access_token,
)

STRICT_SECRET = "super-secret-key-at-least-32-bytes-long!!"


@pytest.fixture
def strict_secret() -> str:
    return STRICT_SECRET


@pytest.fixture
def strict_client(monkeypatch, tmp_path, strict_secret):
    monkeypatch.setenv("DECISIONOS_AUTH_STRICT", "1")
    monkeypatch.setenv("DECISIONOS_JWT_SECRET", strict_secret)
    monkeypatch.setenv("DECISIONOS_SECRET_KEY", "ai-master-key-at-least-32-bytes-long!!")
    app = create_app(tmp_path / "data")
    with TestClient(app) as c:
        yield c


def test_strict_boot_refusal_missing_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("DECISIONOS_AUTH_STRICT", "1")
    monkeypatch.delenv("DECISIONOS_JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="DECISIONOS_AUTH_STRICT=1 requires DECISIONOS_JWT_SECRET to be configured with at least 32 bytes"):
        create_app(tmp_path / "data")


def test_strict_boot_refusal_short_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("DECISIONOS_AUTH_STRICT", "1")
    monkeypatch.setenv("DECISIONOS_JWT_SECRET", "short-secret-under-32-bytes")
    with pytest.raises(RuntimeError, match="DECISIONOS_AUTH_STRICT=1 requires DECISIONOS_JWT_SECRET to be configured with at least 32 bytes"):
        create_app(tmp_path / "data")


def test_dev_mode_boots_without_configured_secret(monkeypatch, tmp_path):
    monkeypatch.delenv("DECISIONOS_AUTH_STRICT", raising=False)
    monkeypatch.delenv("DECISIONOS_JWT_SECRET", raising=False)
    app = create_app(tmp_path / "data")
    assert app is not None


def test_demo_headers_rejected_in_strict_mode(strict_client):
    res = strict_client.get("/v1/pilots", headers={"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"})
    assert res.status_code == 401
    assert "Cryptographically signed Bearer token required" in res.json()["detail"]


def test_forged_signature_rejected(strict_client, strict_secret):
    token = create_access_token("tenant_alpha", "alpha.manager", "ops_manager", secret_key="forged-secret-different-key-32b-min!")
    res = strict_client.get("/v1/pilots", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert "Invalid authentication token" in res.json()["detail"]


def test_expired_token_rejected(strict_client, strict_secret):
    token = create_access_token("tenant_alpha", "alpha.manager", "ops_manager", expires_in_seconds=-60, secret_key=strict_secret)
    res = strict_client.get("/v1/pilots", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert "Token expired" in res.json()["detail"]


def test_cross_tenant_token_isolation(strict_client, strict_secret):
    # Tenant Beta creates a pilot
    beta_token = create_access_token("tenant_beta", "beta.manager", "ops_manager", secret_key=strict_secret)
    res = strict_client.post(
        "/v1/pilots",
        json={"name": "Beta Private Pilot"},
        headers={"Authorization": f"Bearer {beta_token}"},
    )
    assert res.status_code == 201
    beta_pilot_id = res.json()["id"]

    # Tenant Alpha attempts to access Tenant Beta's pilot -> 404
    alpha_token = create_access_token("tenant_alpha", "alpha.manager", "ops_manager", secret_key=strict_secret)
    res = strict_client.get(
        f"/v1/pilots/{beta_pilot_id}",
        headers={"Authorization": f"Bearer {alpha_token}"},
    )
    assert res.status_code == 404

    # Strict mode ignores contradictory X-Tenant: tenant_beta when using Alpha token
    res = strict_client.get(
        f"/v1/pilots/{beta_pilot_id}",
        headers={"Authorization": f"Bearer {alpha_token}", "X-Tenant": "tenant_beta"},
    )
    assert res.status_code == 404


def test_token_mint_endpoint_gated_by_default(strict_client):
    res = strict_client.post("/v1/auth/token", json={"tenant_id": "tenant_alpha"})
    assert res.status_code == 404
    data = res.json()
    assert data["code"] == "not_found"
    assert "disabled" in data["detail"].lower()


def test_token_mint_endpoint_when_allowed(strict_client, monkeypatch):
    monkeypatch.setenv("DECISIONOS_ALLOW_TOKEN_MINT", "1")
    res = strict_client.post(
        "/v1/auth/token",
        json={"tenant_id": "tenant_alpha", "user_id": "alpha.manager", "role": "ops_manager"},
    )
    assert res.status_code == 200
    assert "access_token" in res.json()


MUTATING_ROUTES = [
    ("POST", "/v1/uploads", {"filename": "test.csv"}, "write"),
    ("PUT", "/v1/uploads/up-fake/content", b"fake", "write"),
    ("POST", "/v1/uploads/up-fake/finalize", {}, "write"),
    ("POST", "/v1/datasets/ds-fake/grain-confirmation", {"key_columns": ["case_id"]}, "write"),
    ("POST", "/v1/datasets/ds-fake/revisions/1/publish", {}, "write"),
    ("POST", "/v1/metrics/definitions", {
        "metric_id": "m_test_rbac", "title": "Test", "entity": "case",
        "measures": [], "expression": "1", "dimensions": [],
    }, "metrics_manage"),
    ("POST", "/v1/metrics/definitions/m1/approve", {"version": 1, "change_reason": "test"}, "approve"),
    ("POST", "/v1/metrics/definitions/m1/withdraw", {"version": 1, "change_reason": "test"}, "approve"),
    ("POST", "/v1/forecasts/train", {"dataset_id": "ds", "metric_id": "m"}, "model_create"),
    ("POST", "/v1/scenarios/solve", {"groups": [], "queues": []}, "write"),
    ("POST", "/v1/decisions", {
        "title": "Dec 1",
        "brief": {
            "problem": "p", "relevant_findings": "f", "proposed_action": "a",
            "baseline_option": "b", "scope": "s", "owner": "o", "trade_offs": "t",
            "assumptions": "a", "evidence_coverage": "e", "validation_plan": "v",
            "counter_metrics": "c", "expected_effect": "ef",
        },
    }, "write"),
    ("POST", "/v1/decisions/dec-fake/transition", {"status": "proposed"}, "transition"),
    ("POST", "/v1/decisions/dec-fake/outcome", {"review_verdict": "success"}, "write"),
    ("POST", "/v1/decisions/dec-fake/evidence", {"evidence_id": "ev1"}, "write"),
    ("POST", "/v1/simulations/run", {"num_servers": 2}, "simulate"),
    ("POST", "/v1/monitoring/rules", {"name": "Rule 1", "dataset_id": "ds1", "metric_id": "m1"}, "write"),
    ("PUT", "/v1/monitoring/rules/r-fake", {"name": "Updated"}, "write"),
    ("POST", "/v1/monitoring/evaluate", {}, "write"),
    ("PUT", "/v1/monitoring/episodes/ep-fake/status", {"status": "acknowledged"}, "transition"),
    ("POST", "/v1/evidence", {"investigation_id": "inv-1", "metric_id": "m1"}, "write"),
    ("POST", "/v1/investigations", {"title": "Inv 1", "question": "Why?"}, "write"),
    ("POST", "/v1/investigations/inv-fake/status", {"status": "closed"}, "transition"),
    ("POST", "/v1/investigations/inv-fake/claims", {"statement": "Claim"}, "write"),
    ("POST", "/v1/monitoring/episodes/ep-fake/investigate", {}, "write"),
    ("POST", "/v1/predictive/targets", {"name": "Target 1", "outcome_definition": {}}, "model_create"),
    ("POST", "/v1/predictive/models", {
        "target_id": "t1", "algorithm": "LogisticRegression",
        "training_time_range": {}, "evaluation_time_range": {},
    }, "model_create"),
    ("POST", "/v1/predictive/models/mod-fake/transition", {"status": "active"}, "transition"),
    ("POST", "/v1/predictive/score", {"model_id": "mod-1", "case_id": "c1"}, "write"),
    ("POST", "/v1/predictive/predictions/pred-fake/evidence", {"investigation_id": "inv-1"}, "write"),
    ("POST", "/v1/pilots", {"name": "Pilot 1"}, "manage_pilot"),
    ("POST", "/v1/pilots/pilot-fake/status", {"status": "live"}, "transition"),
    ("POST", "/v1/pilots/pilot-fake/validate-data", {}, "manage_pilot"),
    ("POST", "/v1/pilots/pilot-fake/refresh", {}, "manage_pilot"),
    ("POST", "/v1/pilots/bootstrap", {}, "manage_pilot"),
    ("POST", "/v1/pilots/pilot-fake/mapping", {}, "manage_pilot"),
    ("POST", "/v1/pilots/pilot-fake/sla", {}, "manage_pilot"),
    ("POST", "/v1/pilots/pilot-fake/monitoring-rules", {}, "manage_pilot"),
    ("POST", "/v1/pilots/pilot-fake/risk-target", {}, "manage_pilot"),
]


@pytest.mark.parametrize("method,path,payload,required_permission", MUTATING_ROUTES)
def test_table_driven_role_matrix_viewer_forbidden(strict_client, strict_secret, method, path, payload, required_permission):
    viewer_token = create_access_token("tenant_alpha", "alpha.viewer", "viewer", secret_key=strict_secret)
    headers = {"Authorization": f"Bearer {viewer_token}"}
    if isinstance(payload, bytes):
        res = strict_client.request(method, path, content=payload, headers=headers)
    else:
        res = strict_client.request(method, path, json=payload, headers=headers)

    assert res.status_code == 403
    body = res.json()
    assert body["code"] == "forbidden"
    assert "lacks required permission" in body["detail"]


def test_rbac_specific_role_permissions(strict_client, strict_secret):
    ops_token = create_access_token("tenant_alpha", "alpha.manager", "ops_manager", secret_key=strict_secret)
    modeler_token = create_access_token("tenant_alpha", "alpha.modeler", "semantic_modeler", secret_key=strict_secret)
    qa_token = create_access_token("tenant_alpha", "alpha.qa", "qa_operator", secret_key=strict_secret)

    # 1. ops_manager cannot simulate or create models
    res = strict_client.post("/v1/simulations/run", json={"num_servers": 2}, headers={"Authorization": f"Bearer {ops_token}"})
    assert res.status_code == 403
    assert res.json()["code"] == "forbidden"

    res = strict_client.post("/v1/predictive/targets", json={"name": "T", "outcome_definition": {}}, headers={"Authorization": f"Bearer {ops_token}"})
    assert res.status_code == 403
    assert res.json()["code"] == "forbidden"

    # 2. qa_operator can simulate, but cannot manage pilots or create predictive targets
    res = strict_client.post("/v1/pilots", json={"name": "QA Pilot"}, headers={"Authorization": f"Bearer {qa_token}"})
    assert res.status_code == 403
    assert res.json()["code"] == "forbidden"

    res = strict_client.post("/v1/simulations/run", json={"num_servers": 2}, headers={"Authorization": f"Bearer {qa_token}"})
    assert res.status_code != 403  # QA operator has simulate permission

    # 3. semantic_modeler can create targets and definitions, but cannot manage pilots or approve
    res = strict_client.post("/v1/pilots", json={"name": "Modeler Pilot"}, headers={"Authorization": f"Bearer {modeler_token}"})
    assert res.status_code == 403
    assert res.json()["code"] == "forbidden"


def test_qa_018_metric_approval_rules(strict_client, strict_secret):
    modeler_token = create_access_token("tenant_alpha", "alpha.modeler", "semantic_modeler", secret_key=strict_secret)
    manager_token = create_access_token("tenant_alpha", "alpha.manager", "ops_manager", secret_key=strict_secret)

    # Modeler creates metric definition
    metric_payload = {
        "metric_id": "metric-qa-018-test",
        "name": "QA 018 Test Metric",
        "kind": "ratio",
        "dataset_id": "ds-test",
        "expression": {"kind": "ratio", "numerator_predicates": [{"op": "is_not_null", "field": "first_response_at"}]},
        "eligibility": [{"op": "not_in", "field": "status", "value": ["spam"]}],
        "time_basis": "created_at",
        "timezone": "UTC",
    }
    r = strict_client.post("/v1/metrics/definitions", json=metric_payload, headers={"Authorization": f"Bearer {modeler_token}"})
    assert r.status_code == 201, r.json()

    # Modeler attempts to approve -> 403 forbidden (modeler lacks approve permission)
    r = strict_client.post(
        f"/v1/metrics/definitions/{metric_payload['metric_id']}/approve",
        json={"version": 1, "change_reason": "owner approval attempt"},
        headers={"Authorization": f"Bearer {modeler_token}"},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"

    # Ops manager approves -> 200 approved
    r = strict_client.post(
        f"/v1/metrics/definitions/{metric_payload['metric_id']}/approve",
        json={"version": 1, "change_reason": "ops manager sign-off"},
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

