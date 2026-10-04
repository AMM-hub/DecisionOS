"""Unit and integration tests for WP-05 Executive Pilot Command Center & Summaries."""

import pytest
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app
from decisionos_analytics.pilot import create_pilot


@pytest.fixture
def pilot_ctx(tmp_path):
    data_dir = tmp_path / "data"
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    store = app.state.store
    return app, client, store


def test_pilot_command_center_summary_api(pilot_ctx):
    app, client, store = pilot_ctx
    tenant = "tenant_alpha"
    user = "alpha.manager"
    headers = {"X-Tenant": tenant, "X-User": user}

    # 1. Create Pilot
    plt = create_pilot(store, tenant, "Executive Command Center Test Pilot", user)
    plt_id = plt["id"]

    # 2. GET summary
    res = client.get(f"/v1/pilots/{plt_id}/summary", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert "pilot" in body
    assert "summary" in body

    summary = body["summary"]
    assert "open_alerts" in summary
    assert "high_risk_cases" in summary
    assert "active_investigations" in summary
    assert "open_decisions" in summary
    assert "reviews_due" in summary
    assert "completed_reviews" in summary
    assert summary["auth_security_gate"] == "INTERNAL_EVALUATION_ONLY"


def test_pilot_command_center_tenant_isolation(pilot_ctx):
    app, client, store = pilot_ctx
    alpha_plt = create_pilot(store, "tenant_alpha", "Alpha Pilot", "alpha.manager")

    # Cross tenant access returns 404 (non-disclosing)
    beta_headers = {"X-Tenant": "tenant_beta", "X-User": "beta.manager"}
    res = client.get(f"/v1/pilots/{alpha_plt['id']}/summary", headers=beta_headers)
    assert res.status_code == 404
