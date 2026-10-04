"""WP-01 Guided Onboarding & Configuration Integration Tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from decisionos_analytics.api import create_app


@pytest.fixture
def onboarding_app(tmp_path):
    data_dir = tmp_path / "data"
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    store = app.state.store
    return client, store


def test_pilot_bootstrap_api(onboarding_app):
    client, store = onboarding_app
    alpha_mgr = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
    beta_mgr = {"X-Tenant": "tenant_beta", "X-User": "beta.manager"}

    # 1. Bootstrap Pilot via API
    res = client.post("/v1/pilots/bootstrap", headers=alpha_mgr, json={
        "name": "Golden Support Pilot",
        "domain": "support_ticket_operations",
        "dataset_id": "ds-support-ops",
        "dataset_revision": 1
    })
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "bootstrapped"
    assert data["pilot"]["name"] == "Golden Support Pilot"
    assert data["pilot"]["status"] == "ready_for_evaluation"
    assert data["target"]["id"].startswith("tgt-")
    assert data["model"]["id"].startswith("mdl-")

    # 2. Verify Cross-Tenant Non-Disclosing 404 Security Check
    pilot_id = data["pilot"]["id"]
    assert client.get(f"/v1/pilots/{pilot_id}", headers=beta_mgr).status_code == 404
