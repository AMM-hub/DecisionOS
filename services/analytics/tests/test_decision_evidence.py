"""Tests for WP-03 Decision Evidence Integration (§19 Master Spec & WP-03 prompt)."""

import json
import pytest
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app
from decisionos_analytics.store import now_iso, new_id


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DECISIONOS_STORAGE_DIR", str(data_dir))
    app = create_app(data_dir=data_dir)
    with TestClient(app) as c:
        yield c, app.state.store


def create_test_evidence(store, tenant_id: str, inv_id: str, ev_id: str, user_id: str):
    store.conn.execute(
        """INSERT INTO investigation (
            tenant_id, id, title, question, source_type, owner, created_by, created_at, updated_at
        ) VALUES (?, ?, 'Test Inv', 'Test Q?', 'ad_hoc', ?, ?, ?, ?)""",
        (tenant_id, inv_id, user_id, user_id, now_iso(), now_iso())
    )
    store.conn.execute(
        """INSERT INTO evidence_artifact(
            tenant_id, id, investigation_id, parent_artifact_ids_json, evidence_type, support_status,
            quality_flags_json, metric_id, definition_version, dataset_id, dataset_revision,
            resolved_plan_json, query_params_json, canonical_digest, storage_format, payload_json,
            parquet_key, row_count, exactness_class, reproducibility_status, created_by, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            tenant_id, ev_id, inv_id, "[]", "observed", "supporting",
            "[]", "m_churn", 1, "ds_churn", 1,
            "{}", "{}", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2", "json", '{"churn": 0.15}',
            None, 1, "exact", "reproducible", user_id, now_iso()
        )
    )
    store.conn.commit()


def test_decision_lifecycle_and_evidence_binding(client):
    c, store = client
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # 1. Create a decision in draft
    brief_data = {
        "problem": "High customer churn in segment B",
        "relevant_findings": ["Finding 101"],
        "proposed_action": "Introduce loyalty discount",
        "baseline_option": "Do nothing",
        "scope": "Segment B",
        "owner": "Sarah",
        "trade_offs": ["Lower margin per user"],
        "assumptions": ["Churn caused by pricing"],
        "evidence_coverage": ["Coverage 90%"],
        "validation_plan": "A/B test 4 weeks",
        "counter_metrics": ["Gross margin"],
        "expected_effect": "estimated",
    }
    resp = c.post("/v1/decisions", json={"title": "Churn Mitigation", "brief": brief_data}, headers=headers)
    assert resp.status_code == 201
    decision = resp.json()
    did = decision["id"]
    assert decision["status"] == "draft"

    # 2. Create evidence artifact for tenant_alpha
    ev_id = "ev-alpha-101"
    inv_id = "inv-alpha-101"
    create_test_evidence(store, "tenant_alpha", inv_id, ev_id, "alpha.manager")

    # 3. Bind evidence to decision in draft state
    bind_resp = c.post(
        f"/v1/decisions/{did}/evidence",
        json={"evidence_id": ev_id, "binding_role": "primary_support"},
        headers=headers,
    )
    assert bind_resp.status_code == 201
    binding = bind_resp.json()
    assert binding["decision_id"] == did
    assert binding["evidence_id"] == ev_id
    assert binding["binding_role"] == "primary_support"

    # 4. List decision evidence
    list_resp = c.get(f"/v1/decisions/{did}/evidence", headers=headers)
    assert list_resp.status_code == 200
    ev_list = list_resp.json()
    assert len(ev_list) == 1
    assert ev_list[0]["evidence_id"] == ev_id
    assert ev_list[0]["evidence"]["exactness_class"] == "exact"

    # 5. Transition: draft -> proposed -> accepted
    t1 = c.post(f"/v1/decisions/{did}/transition", json={"status": "proposed", "reason": "Ready for review"}, headers=headers)
    assert t1.status_code == 200
    assert t1.json()["status"] == "proposed"

    t2 = c.post(f"/v1/decisions/{did}/transition", json={"status": "accepted", "reason": "Approved by board"}, headers=headers)
    assert t2.status_code == 200
    assert t2.json()["status"] == "accepted"


def test_accepted_decision_freeze_prevents_direct_evidence_binding(client):
    c, store = client
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # Create & accept decision
    d_resp = c.post(
        "/v1/decisions",
        json={
            "title": "Accepted Decision",
            "brief": {
                "problem": "P", "relevant_findings": [], "proposed_action": "A",
                "baseline_option": "B", "scope": "S", "owner": "O",
                "trade_offs": [], "assumptions": [], "evidence_coverage": [],
                "validation_plan": "V", "counter_metrics": [], "expected_effect": "simulated",
            },
        },
        headers=headers,
    )
    did = d_resp.json()["id"]
    c.post(f"/v1/decisions/{did}/transition", json={"status": "proposed"}, headers=headers)
    c.post(f"/v1/decisions/{did}/transition", json={"status": "accepted"}, headers=headers)

    # Seed evidence artifact
    ev_id = "ev-alpha-102"
    inv_id = "inv-alpha-102"
    create_test_evidence(store, "tenant_alpha", inv_id, ev_id, "alpha.manager")

    # Attempt to bind evidence directly to accepted decision must fail
    bind_fail = c.post(
        f"/v1/decisions/{did}/evidence",
        json={"evidence_id": ev_id, "binding_role": "contributing"},
        headers=headers,
    )
    assert bind_fail.status_code == 422
    assert "frozen" in bind_fail.text.lower()


def test_cross_tenant_evidence_binding_rejected(client):
    c, store = client
    headers_alpha = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # Create decision for Alpha
    d_resp = c.post(
        "/v1/decisions",
        json={
            "title": "Alpha Decision",
            "brief": {
                "problem": "P", "relevant_findings": [], "proposed_action": "A",
                "baseline_option": "B", "scope": "S", "owner": "O",
                "trade_offs": [], "assumptions": [], "evidence_coverage": [],
                "validation_plan": "V", "counter_metrics": [], "expected_effect": "estimated",
            },
        },
        headers=headers_alpha,
    )
    did_alpha = d_resp.json()["id"]

    # Create evidence for Beta
    ev_id_beta = "ev-beta-999"
    inv_id_beta = "inv-beta-999"
    create_test_evidence(store, "tenant_beta", inv_id_beta, ev_id_beta, "beta.manager")

    # Alpha attempts to bind Beta's evidence -> must 404 (non-disclosing)
    bind_resp = c.post(
        f"/v1/decisions/{did_alpha}/evidence",
        json={"evidence_id": ev_id_beta, "binding_role": "primary_support"},
        headers=headers_alpha,
    )
    assert bind_resp.status_code == 404


def test_invalid_status_transitions(client):
    c, store = client
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    d_resp = c.post(
        "/v1/decisions",
        json={
            "title": "Transition Test",
            "brief": {
                "problem": "P", "relevant_findings": [], "proposed_action": "A",
                "baseline_option": "B", "scope": "S", "owner": "O",
                "trade_offs": [], "assumptions": [], "evidence_coverage": [],
                "validation_plan": "V", "counter_metrics": [], "expected_effect": "unknown",
            },
        },
        headers=headers,
    )
    did = d_resp.json()["id"]

    # Invalid status string: non_existent_status
    invalid_resp = c.post(f"/v1/decisions/{did}/transition", json={"status": "non_existent_status"}, headers=headers)
    assert invalid_resp.status_code == 422
    assert "invalid_status" in invalid_resp.text.lower()
