"""Unit and integration tests for WP-02 Semantic, Workflow, SLA, Monitoring, and Risk setup."""

import pytest
from fastapi.testclient import TestClient
from decisionos_analytics.api import create_app
from decisionos_analytics.pilot import SUPPORT_OPERATIONS_SEMANTIC_PACK, create_pilot


@pytest.fixture
def pilot_ctx(tmp_path):
    data_dir = tmp_path / "data"
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    store = app.state.store
    return app, client, store


def test_support_operations_semantic_pack():
    assert len(SUPPORT_OPERATIONS_SEMANTIC_PACK) >= 5
    ids = [m["id"] for m in SUPPORT_OPERATIONS_SEMANTIC_PACK]
    assert "m_ticket_count" in ids
    assert "m_sla_breach_rate" in ids
    assert "m_queue_backlog" in ids


def test_pilot_mapping_and_sla_api(pilot_ctx):
    app, client, store = pilot_ctx
    p = create_pilot(store, "tenant_alpha", "Mapping Test Pilot", "alpha.manager")
    pilot_id = p["id"]

    # 1. Test Mapping Endpoint
    map_res = client.post(
        f"/v1/pilots/{pilot_id}/mapping",
        headers={"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"},
        json={
            "case_id": "ticket_id",
            "activity": "event",
            "timestamp": "created_at",
            "completion_state": "status",
            "queue": "queue",
            "reopen": "reopen",
        },
    )
    assert map_res.status_code == 200
    m_body = map_res.json()
    assert "mapping" in m_body["pilot"]["config"]

    # 2. Test SLA Endpoint with UTC
    sla_res = client.post(
        f"/v1/pilots/{pilot_id}/sla",
        headers={"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"},
        json={
            "target_name": "Standard Support SLA",
            "eligible_population": "all",
            "deadline_rule": "24h",
            "calendar_utc": True,
        },
    )
    assert sla_res.status_code == 200
    assert sla_res.json()["sla_config"]["status_message"] == "SUPPORTED"

    # 3. Test SLA Endpoint with business time (unsupported)
    sla_bus_res = client.post(
        f"/v1/pilots/{pilot_id}/sla",
        headers={"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"},
        json={
            "target_name": "Business Hours SLA",
            "eligible_population": "all",
            "deadline_rule": "24h",
            "calendar_utc": False,
        },
    )
    assert sla_bus_res.status_code == 200
    assert sla_bus_res.json()["sla_config"]["status_message"] == "BUSINESS-TIME SLA NOT SUPPORTED"


def test_pilot_monitoring_and_risk_api(pilot_ctx):
    app, client, store = pilot_ctx
    p = create_pilot(store, "tenant_beta", "Monitoring & Risk Pilot", "beta.manager")
    pilot_id = p["id"]

    # 1. Monitoring Rule setup
    mon_res = client.post(
        f"/v1/pilots/{pilot_id}/monitoring-rules",
        headers={"X-Tenant": "tenant_beta", "X-User": "beta.manager"},
        json={
            "name": "Backlog Spike Rule",
            "metric_id": "m_queue_backlog",
            "threshold": 2.5,
            "method": "seasonal_naive",
        },
    )
    assert mon_res.status_code == 200
    rule = mon_res.json()["rule"]
    assert rule["name"] == "Backlog Spike Rule"
    assert rule["tenant_id"] == "tenant_beta"

    # 2. Risk Target setup
    risk_res = client.post(
        f"/v1/pilots/{pilot_id}/risk-target",
        headers={"X-Tenant": "tenant_beta", "X-User": "beta.manager"},
        json={
            "target_name": "High Priority Breach Target",
            "outcome_window": "24h",
            "approved_feature_contract": [{"feature_id": "case_age_hours"}],
        },
    )
    assert risk_res.status_code == 200
    r_body = risk_res.json()
    assert r_body["risk_config"]["evaluation_state"] == "EVALUATION_ONLY"
    assert r_body["risk_config"]["approval_status"] == "NOT_APPROVED_FOR_REAL_WORLD"
