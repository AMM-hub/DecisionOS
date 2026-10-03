"""WP-02 Investigation Workspace & Claims Unit & Security Tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app
from decisionos_analytics.store import now_iso


@pytest.fixture
def test_app(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    return client, app.state.store


def test_investigation_crud_and_status_transitions(test_app):
    client, store = test_app
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # 1. Create Investigation
    resp = client.post(
        "/v1/investigations",
        headers=headers,
        json={
            "title": "Hospital Capacity Surge",
            "question": "What is driving the ICU bed delay?",
            "source_type": "ad_hoc",
            "alternative_explanations": ["Surgical discharge backlog", "Staff shortage"]
        }
    )
    assert resp.status_code == 201
    inv = resp.json()
    assert inv["id"].startswith("inv-")
    assert inv["status"] == "open"
    inv_id = inv["id"]

    # 2. Get Detail
    get_resp = client.get(f"/v1/investigations/{inv_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["title"] == "Hospital Capacity Surge"

    # 3. Valid Status Transition: open -> in_progress
    trans_resp = client.post(
        f"/v1/investigations/{inv_id}/status",
        headers=headers,
        json={"status": "in_progress"}
    )
    assert trans_resp.status_code == 200
    assert trans_resp.json()["status"] == "in_progress"

    # 4. Invalid Status Transition: in_progress -> invalid_status (422)
    bad_trans = client.post(
        f"/v1/investigations/{inv_id}/status",
        headers=headers,
        json={"status": "non_existent_status"}
    )
    assert bad_trans.status_code == 422


def test_structured_claims_creation(test_app):
    client, store = test_app
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # Create investigation
    inv_resp = client.post(
        "/v1/investigations",
        headers=headers,
        json={"title": "Supply Chain Bottleneck", "question": "Where is the delay?"}
    )
    inv_id = inv_resp.json()["id"]

    # Add Claim
    claim_resp = client.post(
        f"/v1/investigations/{inv_id}/claims",
        headers=headers,
        json={
            "statement": "Port clearance wait time increased by 45%",
            "evidence_type": "observed",
            "support_status": "supporting",
            "structured_fact": {
                "metric_id": "m_clearance_wait",
                "value": 45.0,
                "unit": "percent",
                "period": "2024-Q1"
            }
        }
    )
    assert claim_resp.status_code == 201
    clm = claim_resp.json()
    assert clm["id"].startswith("clm-")
    assert clm["structured_fact"]["metric_id"] == "m_clearance_wait"

    # List claims
    list_clm = client.get(f"/v1/investigations/{inv_id}/claims", headers=headers)
    assert list_clm.status_code == 200
    assert len(list_clm.json()) == 1


def test_idempotent_monitoring_episode_investigation_launch(test_app):
    client, store = test_app
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # Create alert episode in store
    ep_id = "ep-999"
    store.conn.execute(
        """INSERT INTO alert_episode (
            tenant_id, id, rule_id, episode_identity, condition_id, workflow_status, observed_value, expected_lower, expected_upper, started_at
        ) VALUES ('tenant_alpha', ?, 'rule-icu-1', 'ident-1', 'cond-1', 'open', 92.5, 70.0, 85.0, ?)""",
        (ep_id, now_iso())
    )
    store.conn.commit()

    # First Call: 201 Created
    res1 = client.post(f"/v1/monitoring/episodes/{ep_id}/investigate", headers=headers)
    assert res1.status_code == 201
    inv1 = res1.json()
    inv_id1 = inv1["id"]
    assert inv1["source_id"] == ep_id

    # Second Call (Idempotent Retry): 200 OK returning SAME investigation ID
    res2 = client.post(f"/v1/monitoring/episodes/{ep_id}/investigate", headers=headers)
    assert res2.status_code == 200
    inv2 = res2.json()
    assert inv2["id"] == inv_id1


def test_investigation_tenant_isolation(test_app):
    client, store = test_app
    headers_alpha = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
    headers_beta = {"X-Tenant": "tenant_beta", "X-User": "beta.manager"}

    # Create Alpha Investigation
    inv_alpha = client.post(
        "/v1/investigations",
        headers=headers_alpha,
        json={"title": "Alpha Confidential", "question": "Alpha Q?"}
    ).json()["id"]

    # Beta attempts to read Alpha investigation -> 404
    beta_get = client.get(f"/v1/investigations/{inv_alpha}", headers=headers_beta)
    assert beta_get.status_code == 404

    # Beta attempts to add claim to Alpha investigation -> 404
    beta_claim = client.post(
        f"/v1/investigations/{inv_alpha}/claims",
        headers=headers_beta,
        json={"statement": "Tampering statement"}
    )
    assert beta_claim.status_code == 404
