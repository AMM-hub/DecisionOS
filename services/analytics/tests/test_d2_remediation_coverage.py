"""D2 Remediation Regression & Coverage Suite (D2-CERT-004).

High-value regression tests covering:
- Investigation idempotency, episode sources, claims, and error paths
- Evidence sampling controls, un-sampled row limits, non-existent artifact handling
- Decision freeze enforcement on evidence binding and status state machine
- Monitoring alert lifecycle and episode state transitions
- D2 API endpoints negative & error contract validation
"""

from __future__ import annotations

import json
import pytest
import polars as pl
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app
from decisionos_analytics.evidence import (
    capture_evidence, get_evidence, EvidenceError, EvidenceType, SupportStatus,
    MAX_UNSAMPLED_ROWS, compute_canonical_digest
)
from decisionos_analytics.investigations import (
    create_investigation, list_investigations, get_investigation,
    update_investigation_status, add_claim, investigate_episode,
    SourceType, InvestigationStatus, InvestigationError
)
from decisionos_analytics.register import (
    create_decision, get_decision, list_decisions, transition_status, bind_evidence,
    list_decision_evidence, add_amendment, record_outcome, DecisionBrief, DecisionStatus,
    CounterevidenceCheck, CounterevidenceState, BindingRole, OutcomeRecord, Verdict
)
from decisionos_analytics.monitoring import AlertEngine, AlertLifecycle
from decisionos_analytics.semantics import MetricDefinitionContent, MetricQueryRequest, CountExpression
from decisionos_analytics.store import now_iso, new_id


@pytest.fixture
def app_env(tmp_path):
    app = create_app(data_dir=tmp_path / "data")
    client = TestClient(app)
    return client, app.state.store, app.state.objects


def _seed_episode(store, tenant_id: str, rule_id: str, ep_id: str):
    ts = now_iso()
    store.conn.execute("INSERT OR IGNORE INTO tenant (id, name) VALUES (?, ?)", (tenant_id, tenant_id))
    store.conn.execute("INSERT OR IGNORE INTO workspace (tenant_id, id, name) VALUES (?, 'ws-cov', 'Cov Workspace')", (tenant_id,))
    store.conn.execute("INSERT OR IGNORE INTO dataset (tenant_id, id, workspace_id, name, published_revision, created_at) VALUES (?, 'ds-1', 'ws-cov', 'DS 1', 1, ?)", (tenant_id, ts))
    store.conn.execute("INSERT OR IGNORE INTO definition (tenant_id, id, kind, created_by) VALUES (?, 'm-1', 'count', 'creator')", (tenant_id,))
    store.conn.execute(
        """INSERT OR IGNORE INTO alert_rule (tenant_id, id, name, dataset_id, metric_id, owner, created_by, created_at, updated_at)
           VALUES (?, ?, 'Test Rule', 'ds-1', 'm-1', 'owner', 'creator', ?, ?)""",
        (tenant_id, rule_id, ts, ts)
    )
    store.conn.execute(
        """INSERT OR IGNORE INTO alert_episode (tenant_id, id, rule_id, episode_identity, condition_id, started_at)
           VALUES (?, ?, ?, 'ep-ident', 'cond-1', ?)""",
        (tenant_id, ep_id, rule_id, ts)
    )
    store.conn.commit()


def test_investigation_episode_idempotency_and_claims(app_env):
    client, store, objects = app_env
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # 1. Seed tenant & alert episode
    _seed_episode(store, "tenant_alpha", "rule-idemp-cov", "ep-idemp-cov-1")

    # 2. Launch investigation from episode via API twice (idempotency check)
    r1 = client.post("/v1/monitoring/episodes/ep-idemp-cov-1/investigate", headers=headers)
    assert r1.status_code == 201
    inv1 = r1.json()
    assert inv1["source_type"] == "monitoring_episode"
    assert inv1["source_id"] == "ep-idemp-cov-1"

    # Second call returns existing investigation (idempotent)
    r2 = client.post("/v1/monitoring/episodes/ep-idemp-cov-1/investigate", headers=headers)
    assert r2.status_code == 200
    inv2 = r2.json()
    assert inv2["id"] == inv1["id"]

    # 3. Add claim to investigation
    r_claim = client.post(
        f"/v1/investigations/{inv1['id']}/claims",
        headers=headers,
        json={"statement": "Root cause is upstream latency spike", "evidence_artifact_ids": []}
    )
    assert r_claim.status_code == 201
    claim_data = r_claim.json()
    assert claim_data["statement"] == "Root cause is upstream latency spike"

    # 4. Non-existent episode investigation launch -> 404
    r_bogus = client.post("/v1/monitoring/episodes/ep-bogus/investigate", headers=headers)
    assert r_bogus.status_code == 404


def test_evidence_sampling_limits_and_not_found(app_env):
    client, store, objects = app_env
    tenant_id = "tenant_alpha"
    user_id = "alpha.manager"

    store.conn.execute("INSERT OR IGNORE INTO tenant (id, name) VALUES ('tenant_alpha', 'Alpha')")
    store.conn.commit()
    inv = create_investigation(store, tenant_id, "Sampling Test", "Q?", user_id, user_id)

    defn = MetricDefinitionContent(
        metric_id="m_samp", name="M", kind="count", expression=CountExpression(kind="count"),
        eligibility=[], time_basis="x", dataset_id="ds_samp"
    )
    query = MetricQueryRequest(
        schema_version="1.0", metric_id="m_samp", limit=200000, dimensions=["x"],
        window={"start": "2024-01-01T00:00:00Z", "end": "2024-01-31T00:00:00Z", "timezone": "UTC"}
    )
    
    # Over 50,000 rows without allow_sampling -> raises EvidenceError("result_too_large")
    ts_list = [f"2024-01-01T{i//3600:02d}:{(i%3600)//60:02d}:{i%60:02d}Z" for i in range(50001)]
    df_huge = pl.DataFrame({"x": ts_list, "v": [1] * 50001})
    with pytest.raises(EvidenceError) as exc:
        capture_evidence(store, objects, tenant_id, user_id, inv["id"], defn, query, df_huge, dataset_revision=1, allow_sampling=False)
    assert exc.value.code == "result_too_large"

    # Over 100,000 rows with allow_sampling=True -> succeeds with quality_flag "sampled"
    res = capture_evidence(store, objects, tenant_id, user_id, inv["id"], defn, query, df_huge, dataset_revision=1, allow_sampling=True)
    assert "sampled" in res["quality_flags"]
    assert res["row_count"] == 50001

    # Non-existent evidence GET -> raises EvidenceError("evidence_not_found")
    with pytest.raises(EvidenceError) as exc_nf:
        get_evidence(store, objects, tenant_id, "ev-missing-123")
    assert exc_nf.value.code == "evidence_not_found"


def test_decision_freeze_prevents_evidence_binding(app_env):
    client, store, objects = app_env
    tenant_id = "tenant_alpha"
    user_id = "alpha.manager"

    store.conn.execute("INSERT OR IGNORE INTO tenant (id, name) VALUES ('tenant_alpha', 'Alpha')")
    store.conn.execute(
        """INSERT OR IGNORE INTO investigation (
            tenant_id, id, title, question, source_type, owner, created_by, created_at, updated_at
        ) VALUES ('tenant_alpha', 'inv-1', 'Title', 'Q?', 'ad_hoc', 'alpha.manager', 'alpha.manager', ?, ?)""",
        (now_iso(), now_iso())
    )
    store.conn.commit()
    brief = DecisionBrief(
        problem="Freeze test", relevant_findings=[], proposed_action="Action",
        baseline_option="Base", scope="Scope", owner=user_id, trade_offs=[],
        assumptions=[], evidence_coverage=[], validation_plan="Plan",
        counter_metrics=[], expected_effect="deterministic"
    )
    dec = create_decision(store.conn, tenant_id, "Freeze Dec", brief, user_id)
    
    # Setup mock evidence record in DB
    store.conn.execute(
        """INSERT INTO evidence_artifact (
            tenant_id, id, investigation_id, parent_artifact_ids_json, evidence_type, support_status,
            quality_flags_json, metric_id, definition_version, dataset_id, dataset_revision,
            resolved_plan_json, query_params_json, canonical_digest, storage_format, payload_json,
            row_count, exactness_class, reproducibility_status, created_by, created_at
        ) VALUES (?, 'ev-bind-1', 'inv-1', '[]', 'observed', 'supporting', '[]', 'm1', 1, 'd1', 1, '{}', '{}', 'digest', 'json', '[]', 0, 'exact', 'fully_reproducible', ?, ?)""",
        (tenant_id, user_id, now_iso())
    )
    store.conn.commit()

    # Bind evidence in DRAFT status -> succeeds
    b1 = bind_evidence(store.conn, tenant_id, dec.id, "ev-bind-1", BindingRole.PRIMARY_SUPPORT, user_id)
    assert b1["binding_role"] == "primary_support"

    # Transition decision through ACCEPTED
    transition_status(store.conn, tenant_id, dec.id, DecisionStatus.PROPOSED, user_id, "propose")
    transition_status(store.conn, tenant_id, dec.id, DecisionStatus.ACCEPTED, user_id, "accept")

    # Attempt binding to ACCEPTED decision -> raises ValueError ("context is frozen")
    with pytest.raises(ValueError, match="context is frozen"):
        bind_evidence(store.conn, tenant_id, dec.id, "ev-bind-1", BindingRole.CONTRIBUTING, user_id)


def test_monitoring_episode_lifecycle_and_rules(app_env):
    _, store, _ = app_env
    tenant_id = "tenant_alpha"
    user_id = "alpha.tester"

    _seed_episode(store, tenant_id, "rule-life-cov", "ep-life-cov-1")

    # Valid transitions: open -> acknowledged -> investigating -> resolved
    ep1 = AlertLifecycle.transition_episode(tenant_id, "ep-life-cov-1", "acknowledged", user_id, store)
    assert ep1["workflow_status"] == "acknowledged"

    ep2 = AlertLifecycle.transition_episode(tenant_id, "ep-life-cov-1", "investigating", user_id, store)
    assert ep2["workflow_status"] == "investigating"

    ep3 = AlertLifecycle.transition_episode(tenant_id, "ep-life-cov-1", "resolved", user_id, store)
    assert ep3["workflow_status"] == "resolved"

    # Non-existent episode transition -> raises LookupError/ValueError
    with pytest.raises((ValueError, LookupError)):
        AlertLifecycle.transition_episode(tenant_id, "ep-missing", "acknowledged", user_id, store)


def test_investigation_and_decision_edge_coverage(app_env):
    client, store, _ = app_env
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # 1. GET /v1/investigations with query param filters (status, owner, source_type)
    r_create = client.post(
        "/v1/investigations",
        headers=headers,
        json={"title": "Edge Test", "question": "Why edge?", "source_type": "ad_hoc", "owner": "alpha.manager"}
    )
    assert r_create.status_code == 201
    inv_id = r_create.json()["id"]

    r_list = client.get("/v1/investigations?status=open&owner=alpha.manager&source_type=ad_hoc", headers=headers)
    assert r_list.status_code == 200
    assert len(r_list.json()) >= 1

    # 2. GET /v1/investigations/{id} and claims endpoint
    r_get = client.get(f"/v1/investigations/{inv_id}", headers=headers)
    assert r_get.status_code == 200

    r_claims = client.get(f"/v1/investigations/{inv_id}/claims", headers=headers)
    assert r_claims.status_code == 200
    assert isinstance(r_claims.json(), list)

    # 3. GET /v1/investigations/{id}/claims on bogus id -> 404
    assert client.get("/v1/investigations/inv-bogus/claims", headers=headers).status_code == 404

    # 4. POST malformed investigation creation -> 422
    r_bad_inv = client.post("/v1/investigations", headers=headers, json={"title": "No Question"})
    assert r_bad_inv.status_code == 422

    # 5. POST malformed claim creation -> 422
    r_bad_claim = client.post(f"/v1/investigations/{inv_id}/claims", headers=headers, json={})
    assert r_bad_claim.status_code == 422

    # 6. POST status update on investigation with invalid status string -> 422
    r_bad_st = client.post(f"/v1/investigations/{inv_id}/status", headers=headers, json={"status": "invalid_status_enum"})
    assert r_bad_st.status_code == 422


def test_register_duplicate_binding_and_outcome(app_env):
    _, store, _ = app_env
    tenant_id = "tenant_alpha"
    user_id = "alpha.manager"

    store.conn.execute("INSERT OR IGNORE INTO tenant (id, name) VALUES ('tenant_alpha', 'Alpha')")
    store.conn.execute(
        """INSERT OR IGNORE INTO investigation (
            tenant_id, id, title, question, source_type, owner, created_by, created_at, updated_at
        ) VALUES ('tenant_alpha', 'inv-dup-1', 'Title', 'Q?', 'ad_hoc', 'alpha.manager', 'alpha.manager', ?, ?)""",
        (now_iso(), now_iso())
    )
    brief = DecisionBrief(
        problem="Dup test", relevant_findings=[], proposed_action="Action",
        baseline_option="Base", scope="Scope", owner=user_id, trade_offs=[],
        assumptions=[], evidence_coverage=[], validation_plan="Plan",
        counter_metrics=[], expected_effect="deterministic"
    )
    dec = create_decision(store.conn, tenant_id, "Dup Dec", brief, user_id)

    store.conn.execute(
        """INSERT INTO evidence_artifact (
            tenant_id, id, investigation_id, parent_artifact_ids_json, evidence_type, support_status,
            quality_flags_json, metric_id, definition_version, dataset_id, dataset_revision,
            resolved_plan_json, query_params_json, canonical_digest, storage_format, payload_json,
            row_count, exactness_class, reproducibility_status, created_by, created_at
        ) VALUES (?, 'ev-dup-1', 'inv-dup-1', '[]', 'observed', 'supporting', '[]', 'm1', 1, 'd1', 1, '{}', '{}', 'digest', 'json', '[]', 0, 'exact', 'fully_reproducible', ?, ?)""",
        (tenant_id, user_id, now_iso())
    )
    store.conn.commit()

    # Same binding role -> returns existing binding (idempotent)
    b1 = bind_evidence(store.conn, tenant_id, dec.id, "ev-dup-1", BindingRole.PRIMARY_SUPPORT, user_id)
    b2 = bind_evidence(store.conn, tenant_id, dec.id, "ev-dup-1", BindingRole.PRIMARY_SUPPORT, user_id)
    assert b1["id"] == b2["id"]

    # Different binding role -> raises ValueError
    with pytest.raises(ValueError, match="already bound"):
        bind_evidence(store.conn, tenant_id, dec.id, "ev-dup-1", BindingRole.CONTRIBUTING, user_id)


def test_more_investigation_error_paths(app_env):
    client, store, _ = app_env
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # 1. Create investigation referencing non-existent monitoring episode source -> 404
    r_no_src = client.post(
        "/v1/investigations",
        headers=headers,
        json={"title": "Missing Source", "question": "Q?", "source_type": "monitoring_episode", "source_id": "ep-non-existent"}
    )
    assert r_no_src.status_code == 404

    # 2. Add claim referencing non-existent evidence ID -> 404
    r_inv = client.post(
        "/v1/investigations",
        headers=headers,
        json={"title": "Claim Evidence Test", "question": "Q?", "source_type": "ad_hoc"}
    )
    assert r_inv.status_code == 201
    inv_id = r_inv.json()["id"]

    r_no_ev = client.post(
        f"/v1/investigations/{inv_id}/claims",
        headers=headers,
        json={"statement": "Claim with missing evidence", "evidence_id": "ev-non-existent"}
    )
    assert r_no_ev.status_code == 404

    # 3. Update investigation status to invalid transition (e.g., closed -> in_progress)
    client.post(f"/v1/investigations/{inv_id}/status", headers=headers, json={"status": "closed"})
    r_inv_trans = client.post(f"/v1/investigations/{inv_id}/status", headers=headers, json={"status": "in_progress"})
    assert r_inv_trans.status_code == 422


