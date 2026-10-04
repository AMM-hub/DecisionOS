"""WP-05 Tenant Security & Cross-Tenant Integrity Regression Tests."""

import sqlite3
import pytest
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app
from decisionos_analytics.store import now_iso, new_id


@pytest.fixture
def client(tmp_path):
    data_dir = tmp_path / "data"
    app = create_app(data_dir=data_dir)
    with TestClient(app) as c:
        yield c, app.state.store


def seed_investigation(store, tenant_id: str, inv_id: str, owner: str):
    store.conn.execute(
        """INSERT INTO investigation (
            tenant_id, id, title, question, source_type, owner, created_by, created_at, updated_at
        ) VALUES (?, ?, 'Surge Study', 'Why beds filled?', 'ad_hoc', ?, ?, ?, ?)""",
        (tenant_id, inv_id, owner, owner, now_iso(), now_iso())
    )
    store.conn.commit()


def seed_evidence(store, tenant_id: str, inv_id: str, ev_id: str, owner: str):
    store.conn.execute(
        """INSERT INTO evidence_artifact(
            tenant_id, id, investigation_id, parent_artifact_ids_json, evidence_type, support_status,
            quality_flags_json, metric_id, definition_version, dataset_id, dataset_revision,
            resolved_plan_json, query_params_json, canonical_digest, storage_format, payload_json,
            parquet_key, row_count, exactness_class, reproducibility_status, created_by, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            tenant_id, ev_id, inv_id, "[]", "observed", "supporting",
            "[]", "m_icu", 1, "ds_icu", 1,
            "{}", "{}", "digest_alpha_sec_12345678901234567890123456789012345678901234567890", "json", '{"icu": 85}',
            None, 1, "exact", "reproducible", owner, now_iso()
        )
    )
    store.conn.commit()


def test_tenant_isolation_investigations_read_and_mutation(client):
    c, store = client
    alpha_mgr = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
    beta_mgr = {"X-Tenant": "tenant_beta", "X-User": "beta.manager"}

    inv_alpha = "inv-sec-alpha-001"
    seed_investigation(store, "tenant_alpha", inv_alpha, "alpha.manager")

    # Alpha manager accesses Alpha investigation -> 200 OK
    r_ok = c.get(f"/v1/investigations/{inv_alpha}", headers=alpha_mgr)
    assert r_ok.status_code == 200

    # Beta manager accesses Alpha investigation -> 404 (non-disclosing)
    r_cross = c.get(f"/v1/investigations/{inv_alpha}", headers=beta_mgr)
    assert r_cross.status_code == 404

    # Header mismatch: tenant_beta header with alpha.manager user -> 404
    r_mismatch = c.get(f"/v1/investigations/{inv_alpha}", headers={"X-Tenant": "tenant_beta", "X-User": "alpha.manager"})
    assert r_mismatch.status_code == 404

    # Missing user header -> 401
    r_nouser = c.get(f"/v1/investigations/{inv_alpha}", headers={"X-Tenant": "tenant_alpha"})
    assert r_nouser.status_code == 401

    # Invalid user header -> 401
    r_invalid = c.get(f"/v1/investigations/{inv_alpha}", headers={"X-Tenant": "tenant_alpha", "X-User": "bogus.user"})
    assert r_invalid.status_code == 401


def test_cross_tenant_claim_creation_prevented(client):
    c, store = client
    beta_mgr = {"X-Tenant": "tenant_beta", "X-User": "beta.manager"}

    inv_alpha = "inv-sec-alpha-002"
    seed_investigation(store, "tenant_alpha", inv_alpha, "alpha.manager")

    # Beta attempts to post claim to Alpha investigation -> 404
    r_claim = c.post(
        f"/v1/investigations/{inv_alpha}/claims",
        headers=beta_mgr,
        json={"statement": "Cross tenant claim", "evidence_type": "observed", "support_status": "supporting"},
    )
    assert r_claim.status_code == 404

    # Database state unchanged
    claims = store.conn.execute("SELECT id FROM investigation_claim WHERE investigation_id=?", (inv_alpha,)).fetchall()
    assert len(claims) == 0


def test_cross_tenant_evidence_retrieval_and_binding(client):
    c, store = client
    beta_mgr = {"X-Tenant": "tenant_beta", "X-User": "beta.manager"}

    inv_alpha = "inv-sec-alpha-003"
    ev_alpha = "ev-sec-alpha-003"
    seed_investigation(store, "tenant_alpha", inv_alpha, "alpha.manager")
    seed_evidence(store, "tenant_alpha", inv_alpha, ev_alpha, "alpha.manager")

    # Beta attempts to fetch Alpha's evidence -> 404
    r_ev = c.get(f"/v1/evidence/{ev_alpha}", headers=beta_mgr)
    assert r_ev.status_code == 404


def test_database_level_cross_tenant_foreign_keys(client):
    _, store = client

    # Enable FKs
    store.conn.execute("PRAGMA foreign_keys = ON;")

    inv_alpha = "inv-fk-alpha"
    inv_beta = "inv-fk-beta"
    ev_alpha = "ev-fk-alpha"

    seed_investigation(store, "tenant_alpha", inv_alpha, "alpha.manager")
    seed_investigation(store, "tenant_beta", inv_beta, "beta.manager")
    seed_evidence(store, "tenant_alpha", inv_alpha, ev_alpha, "alpha.manager")

    # Attempt cross-tenant claim (Tenant Beta claim referencing Tenant Alpha evidence)
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            """INSERT INTO investigation_claim(
                tenant_id, id, investigation_id, evidence_id, statement, created_by, created_at
            ) VALUES ('tenant_beta', 'claim-cross', ?, ?, 'Invalid Cross FK', 'beta.manager', ?)""",
            (inv_beta, ev_alpha, now_iso())
        )
        store.conn.commit()

    # Attempt cross-tenant decision evidence binding (Tenant Beta decision referencing Tenant Alpha evidence)
    dec_beta = new_id()
    store.conn.execute(
        "INSERT INTO decision(tenant_id, id, title, brief_json, created_by, created_at, updated_at) VALUES ('tenant_beta', ?, 'Beta Dec', '{}', 'beta.manager', ?, ?)",
        (dec_beta, now_iso(), now_iso())
    )
    store.conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            "INSERT INTO decision_evidence_binding(tenant_id, id, decision_id, evidence_id, binding_role, bound_by, bound_at) VALUES ('tenant_beta', ?, ?, ?, 'primary_support', 'beta.manager', ?)",
            (new_id(), dec_beta, ev_alpha, now_iso())
        )
        store.conn.commit()
