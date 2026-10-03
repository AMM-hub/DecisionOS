"""WP-05 End-to-End Operational Decision Loop, Immutability & Idempotency Integration Tests."""

import json
import pytest
import polars as pl
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app
from decisionos_analytics.store import now_iso, new_id


@pytest.fixture
def test_env(tmp_path):
    data_dir = tmp_path / "data"
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    store = app.state.store
    objects = app.state.objects
    return client, store, objects


def seed_alert_episode(store, tenant_id: str, rule_id: str, ep_id: str):
    ts = now_iso()
    store.conn.execute(
        """INSERT INTO alert_rule (tenant_id, id, name, dataset_id, metric_id, owner, created_by, created_at, updated_at)
           VALUES (?, ?, 'SLA Spike Rule', 'ds-ops', 'm_sla', 'alpha.manager', 'alpha.manager', ?, ?)""",
        (tenant_id, rule_id, ts, ts)
    )
    store.conn.execute(
        """INSERT INTO alert_episode (tenant_id, id, rule_id, episode_identity, condition_id, started_at)
           VALUES (?, ?, ?, 'ep-ident-1', 'cond-1', ?)""",
        (tenant_id, ep_id, rule_id, ts)
    )
    store.conn.commit()


def seed_certified_metric(store, objects, tenant_id: str, dataset_id: str, metric_id: str, rev_no: int = 1):
    store.conn.execute(
        "INSERT INTO dataset (tenant_id, id, workspace_id, name, published_revision, created_at) VALUES (?, ?, 'ws-support-ops', 'Ops Data', ?, ?)",
        (tenant_id, dataset_id, rev_no, now_iso())
    )
    import io
    buf = io.BytesIO()
    df = pl.DataFrame({"timestamp": ["2024-01-01T10:00:00Z"], "delay": [45]})
    df.write_parquet(buf)
    obj_res = objects.put_revision_object(tenant_id, dataset_id, rev_no, f"rev-{rev_no}.parquet", buf.getvalue())

    manifest = {"objects": [{"key": obj_res["key"]}]}
    store.conn.execute(
        "INSERT INTO dataset_revision (tenant_id, dataset_id, revision, state, manifest, row_count, created_at) VALUES (?, ?, ?, 'published', ?, 1, ?)",
        (tenant_id, dataset_id, rev_no, json.dumps(manifest), now_iso())
    )
    store.conn.execute(
        "INSERT INTO definition (tenant_id, id, kind, created_by) VALUES (?, ?, 'count', 'alpha.manager')",
        (tenant_id, metric_id)
    )
    defn_content = {
        "metric_id": metric_id,
        "name": "Discharge Delay",
        "kind": "count",
        "expression": {"kind": "count", "predicates": []},
        "eligibility": [],
        "time_basis": "timestamp",
        "timezone": "UTC",
        "dataset_id": dataset_id,
    }
    store.conn.execute(
        "INSERT INTO definition_version (tenant_id, definition_id, version, content, created_by, created_at) VALUES (?, ?, 1, ?, 'alpha.manager', ?)",
        (tenant_id, metric_id, json.dumps(defn_content), now_iso())
    )
    store.conn.execute(
        """INSERT INTO definition_publication (
            tenant_id, definition_id, version, semantic_release_id, effective_from, published_at, approved_by, change_reason
        ) VALUES (?, ?, 1, 'rel-1', ?, ?, 'alpha.manager', 'initial')""",
        (tenant_id, metric_id, now_iso(), now_iso())
    )
    store.conn.commit()


def test_full_operational_decision_loop(test_env):
    client, store, objects = test_env
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # 1. Monitoring Episode
    rule_id = "rule-icu-01"
    ep_id = "ep-icu-01"
    seed_alert_episode(store, "tenant_alpha", rule_id, ep_id)

    # 2. Launch Investigation from Episode
    inv_resp = client.post(f"/v1/monitoring/episodes/{ep_id}/investigate", headers=headers)
    assert inv_resp.status_code == 201
    inv = inv_resp.json()
    inv_id = inv["id"]
    assert inv["source_type"] == "monitoring_episode"

    # 3. Add Structured Claim
    claim_resp = client.post(
        f"/v1/investigations/{inv_id}/claims",
        headers=headers,
        json={
            "statement": "Discharge delays caused 40% of bed shortages",
            "evidence_type": "observed",
            "support_status": "supporting",
            "structured_fact": {"metric_id": "m_delay", "value": 40, "unit": "percent"},
        },
    )
    assert claim_resp.status_code == 201
    claim = claim_resp.json()
    assert claim["statement"].startswith("Discharge delays")

    # 4. Seed metric and capture Evidence Artifact
    seed_certified_metric(store, objects, "tenant_alpha", "ds-ops", "m_delay", 1)
    ev_resp = client.post(
        "/v1/evidence",
        headers=headers,
        json={
            "investigation_id": inv_id,
            "metric_id": "m_delay",
            "evidence_type": "observed",
            "support_status": "supporting",
        },
    )
    assert ev_resp.status_code == 201
    evidence = ev_resp.json()
    ev_id = evidence["artifact_id"]

    # 5. Create Decision Brief
    dec_resp = client.post(
        "/v1/decisions",
        headers=headers,
        json={
            "title": "Hospital ICU Reallocation",
            "brief": {
                "problem": inv["question"],
                "relevant_findings": [claim["statement"]],
                "proposed_action": "Add 4 step-down beds",
                "baseline_option": "Status quo",
                "scope": "ICU Ward B",
                "owner": "alpha.manager",
                "trade_offs": ["Increased staffing cost"],
                "assumptions": ["Surge persists"],
                "evidence_coverage": [ev_id],
                "validation_plan": "Evaluate in 30 days",
                "counter_metrics": [],
                "expected_effect": "simulated",
            },
        },
    )
    assert dec_resp.status_code == 201
    dec_id = dec_resp.json()["id"]

    # 6. Bind Evidence to Decision Brief
    bind_resp = client.post(
        f"/v1/decisions/{dec_id}/evidence",
        headers=headers,
        json={"evidence_id": ev_id, "binding_role": "primary_support"},
    )
    assert bind_resp.status_code == 201

    # 7. Lifecycle transitions: draft -> proposed -> accepted
    p_resp = client.post(f"/v1/decisions/{dec_id}/transition", headers=headers, json={"status": "proposed"})
    assert p_resp.status_code == 200

    a_resp = client.post(f"/v1/decisions/{dec_id}/transition", headers=headers, json={"status": "accepted"})
    assert a_resp.status_code == 200
    assert a_resp.json()["status"] == "accepted"

    # 8. Verify context frozen
    bind_after_accept = client.post(
        f"/v1/decisions/{dec_id}/evidence",
        headers=headers,
        json={"evidence_id": ev_id, "binding_role": "contributing"},
    )
    assert bind_after_accept.status_code == 422
    assert "frozen" in bind_after_accept.text.lower()


def test_idempotent_episode_investigation_launch(test_env):
    client, store, _ = test_env
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    seed_alert_episode(store, "tenant_alpha", "rule-idemp", "ep-idemp-1")

    # First launch -> 201 Created
    r1 = client.post("/v1/monitoring/episodes/ep-idemp-1/investigate", headers=headers)
    assert r1.status_code == 201
    inv_id1 = r1.json()["id"]

    # Repeated launch -> 200 OK returning same investigation ID
    r2 = client.post("/v1/monitoring/episodes/ep-idemp-1/investigate", headers=headers)
    assert r2.status_code == 200
    inv_id2 = r2.json()["id"]
    assert inv_id1 == inv_id2

    # Database contains exactly ONE investigation
    rows = store.conn.execute("SELECT id FROM investigation WHERE tenant_id='tenant_alpha' AND source_id='ep-idemp-1'").fetchall()
    assert len(rows) == 1


def test_evidence_immutability_across_dataset_revisions(test_env):
    client, store, objects = test_env
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # Seed episode & investigation
    seed_alert_episode(store, "tenant_alpha", "rule-rev", "ep-rev-1")
    inv = client.post("/v1/monitoring/episodes/ep-rev-1/investigate", headers=headers).json()

    # Revision 1
    seed_certified_metric(store, objects, "tenant_alpha", "ds-rev", "m_rev", rev_no=1)
    ev1 = client.post("/v1/evidence", headers=headers, json={"investigation_id": inv["id"], "metric_id": "m_rev"}).json()
    digest1 = ev1["canonical_digest"]
    assert ev1["dataset_revision"] == 1

    # Publish Revision 2
    store.conn.execute("UPDATE dataset SET published_revision=2 WHERE tenant_id='tenant_alpha' AND id='ds-rev'")
    import io
    buf = io.BytesIO()
    df2 = pl.DataFrame({"timestamp": ["2024-01-01T10:00:00Z"], "delay": [999]})
    df2.write_parquet(buf)
    obj_res2 = objects.put_revision_object("tenant_alpha", "ds-rev", 2, "rev-2.parquet", buf.getvalue())
    manifest2 = {"objects": [{"key": obj_res2["key"]}]}
    store.conn.execute(
        "INSERT INTO dataset_revision (tenant_id, dataset_id, revision, state, manifest, row_count, created_at) VALUES (?, 'ds-rev', 2, 'published', ?, 1, ?)",
        ("tenant_alpha", json.dumps(manifest2), now_iso())
    )
    store.conn.commit()

    # Capture Evidence 2
    ev2 = client.post("/v1/evidence", headers=headers, json={"investigation_id": inv["id"], "metric_id": "m_rev"}).json()
    assert ev2["dataset_revision"] == 2

    # Evidence 1 remains unchanged in store
    ev1_fetched = client.get(f"/v1/evidence/{ev1['artifact_id']}", headers=headers).json()
    assert ev1_fetched["canonical_digest"] == digest1
    assert ev1_fetched["dataset_revision"] == 1


def test_digest_tamper_detection(test_env):
    client, store, objects = test_env
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    seed_alert_episode(store, "tenant_alpha", "rule-tamper", "ep-tamper-1")
    inv = client.post("/v1/monitoring/episodes/ep-tamper-1/investigate", headers=headers).json()
    seed_certified_metric(store, objects, "tenant_alpha", "ds-tamper", "m_tamper", 1)

    ev = client.post("/v1/evidence", headers=headers, json={"investigation_id": inv["id"], "metric_id": "m_tamper"}).json()
    ev_id = ev["artifact_id"]

    # Tamper with stored JSON payload in SQLite
    store.conn.execute(
        "UPDATE evidence_artifact SET payload_json='[{\"tampered\": true}]' WHERE tenant_id='tenant_alpha' AND id=?",
        (ev_id,)
    )
    store.conn.commit()

    # GET evidence detects digest mismatch & sets quality_flags or integrity status
    res = client.get(f"/v1/evidence/{ev_id}", headers=headers).json()
    assert "integrity_mismatch" in res["quality_flags"]
