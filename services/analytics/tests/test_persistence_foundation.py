"""WP-00 Persistence Foundation & Composite Tenant Integrity Tests."""

from __future__ import annotations

import sqlite3
import pytest
from decisionos_analytics.store import Store, new_id, now_iso


def test_schema_initialization(tmp_path):
    db_path = tmp_path / "control.sqlite3"
    store = Store(db_path)
    # Check tables exist
    tables = [
        row[0]
        for row in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    assert "investigation" in tables
    assert "evidence_artifact" in tables
    assert "investigation_claim" in tables
    assert "decision_evidence_binding" in tables
    store.close()


def test_composite_tenant_integrity_enforcement(tmp_path):
    db_path = tmp_path / "control.sqlite3"
    store = Store(db_path)
    conn = store.conn

    # Setup tenant alpha and beta
    conn.execute("INSERT INTO tenant VALUES ('tenant_alpha', 'Alpha Inc')")
    conn.execute("INSERT INTO tenant VALUES ('tenant_beta', 'Beta Inc')")
    conn.commit()

    # Create investigation for tenant_alpha
    inv_id = new_id()
    conn.execute(
        "INSERT INTO investigation(tenant_id, id, title, question, source_type, owner, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        ("tenant_alpha", inv_id, "Delay Investigation", "Why is delay high?", "ad_hoc", "owner1", "user1", now_iso(), now_iso()),
    )
    conn.commit()

    # Create evidence for tenant_alpha
    ev_id = new_id()
    conn.execute(
        """INSERT INTO evidence_artifact(
            tenant_id, id, investigation_id, metric_id, dataset_id, resolved_plan_json, canonical_digest, created_by, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?)""",
        ("tenant_alpha", ev_id, inv_id, "metric1", "ds1", "{}", "sha256_dummy", "user1", now_iso()),
    )
    conn.commit()

    # Cross-tenant FK attempt: Tenant Beta trying to reference Tenant Alpha's investigation
    ev_cross_id = new_id()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO evidence_artifact(
                tenant_id, id, investigation_id, metric_id, dataset_id, resolved_plan_json, canonical_digest, created_by, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?)""",
            ("tenant_beta", ev_cross_id, inv_id, "metric1", "ds1", "{}", "sha256_dummy", "user2", now_iso()),
        )
        conn.commit()

    store.close()


def test_decision_evidence_binding_tenant_isolation(tmp_path):
    db_path = tmp_path / "control.sqlite3"
    store = Store(db_path)
    conn = store.conn

    conn.execute("INSERT INTO tenant VALUES ('tenant_alpha', 'Alpha Inc')")
    conn.execute("INSERT INTO tenant VALUES ('tenant_beta', 'Beta Inc')")

    # Create Alpha decision
    dec_alpha = new_id()
    conn.execute(
        "INSERT INTO decision(tenant_id, id, title, brief_json, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        ("tenant_alpha", dec_alpha, "Alpha Decision", "{}", "user1", now_iso(), now_iso()),
    )

    # Create Alpha investigation and evidence
    inv_alpha = new_id()
    conn.execute(
        "INSERT INTO investigation(tenant_id, id, title, question, owner, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        ("tenant_alpha", inv_alpha, "Alpha Inv", "Question", "owner1", "user1", now_iso(), now_iso()),
    )

    ev_alpha = new_id()
    conn.execute(
        """INSERT INTO evidence_artifact(
            tenant_id, id, investigation_id, metric_id, dataset_id, resolved_plan_json, canonical_digest, created_by, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?)""",
        ("tenant_alpha", ev_alpha, inv_alpha, "metric1", "ds1", "{}", "sha256_alpha", "user1", now_iso()),
    )
    conn.commit()

    # Valid binding
    bind_id = new_id()
    conn.execute(
        "INSERT INTO decision_evidence_binding(tenant_id, id, decision_id, evidence_id, role, created_at) VALUES (?,?,?,?,?,?)",
        ("tenant_alpha", bind_id, dec_alpha, ev_alpha, "primary_support", now_iso()),
    )
    conn.commit()

    # Duplicate binding should fail
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO decision_evidence_binding(tenant_id, id, decision_id, evidence_id, role, created_at) VALUES (?,?,?,?,?,?)",
            ("tenant_alpha", new_id(), dec_alpha, ev_alpha, "primary_support", now_iso()),
        )
        conn.commit()

    # Cross-tenant binding: Tenant Beta decision referencing Tenant Alpha evidence
    dec_beta = new_id()
    conn.execute(
        "INSERT INTO decision(tenant_id, id, title, brief_json, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        ("tenant_beta", dec_beta, "Beta Decision", "{}", "user2", now_iso(), now_iso()),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO decision_evidence_binding(tenant_id, id, decision_id, evidence_id, role, created_at) VALUES (?,?,?,?,?,?)",
            ("tenant_beta", new_id(), dec_beta, ev_alpha, "primary_support", now_iso()),
        )
        conn.commit()

    store.close()
