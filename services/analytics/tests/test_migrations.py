"""R10 schema migration tests.

Covers fresh installs, upgrades of the pre-migration (v0) database, the
boot-time future-version guard, idempotent re-runs, and proof that the repaired
composite foreign key is actually enforced.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from decisionos_analytics.migrations import MIGRATIONS, apply_pending

LIVE_DB = Path(__file__).resolve().parents[1] / "var" / "worker" / "control.sqlite3"
CODE_MAX = max(version for version, _, _ in MIGRATIONS)

_V0_SCHEMA = """
CREATE TABLE tenant (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL
);
INSERT INTO tenant VALUES ('tenant_alpha', 'Northline Telecom (synthetic)');

CREATE TABLE investigation (
  tenant_id TEXT NOT NULL REFERENCES tenant(id),
  id TEXT NOT NULL,
  title TEXT NOT NULL,
  question TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'ad_hoc',
  source_id TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  owner TEXT NOT NULL,
  analytical_state_json TEXT NOT NULL DEFAULT '{}',
  alternative_explanations_json TEXT NOT NULL DEFAULT '[]',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, id)
);

CREATE TABLE evidence_artifact (
  tenant_id TEXT NOT NULL REFERENCES tenant(id),
  id TEXT NOT NULL,
  investigation_id TEXT NOT NULL,
  parent_artifact_ids_json TEXT NOT NULL DEFAULT '[]',
  evidence_type TEXT NOT NULL DEFAULT 'observed',
  support_status TEXT NOT NULL DEFAULT 'supporting',
  quality_flags_json TEXT NOT NULL DEFAULT '[]',
  metric_id TEXT NOT NULL,
  definition_version INTEGER NOT NULL DEFAULT 1,
  dataset_id TEXT NOT NULL,
  dataset_revision INTEGER NOT NULL DEFAULT 1,
  resolved_plan_json TEXT NOT NULL DEFAULT '{}',
  query_params_json TEXT NOT NULL DEFAULT '{}',
  canonical_digest TEXT NOT NULL,
  storage_format TEXT NOT NULL DEFAULT 'json',
  payload_json TEXT,
  parquet_key TEXT,
  row_count INTEGER NOT NULL DEFAULT 0,
  exactness_class TEXT NOT NULL DEFAULT 'exact',
  reproducibility_status TEXT NOT NULL DEFAULT 'reproducible',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, investigation_id) REFERENCES investigation(tenant_id, id)
);

CREATE TABLE decision (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  brief_json TEXT NOT NULL,
  counterevidence_json TEXT NOT NULL DEFAULT '[]',
  amendments_json TEXT NOT NULL DEFAULT '[]',
  outcome_json TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE decision_evidence_binding (
  tenant_id TEXT NOT NULL REFERENCES tenant(id),
  id TEXT NOT NULL,
  decision_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  binding_role TEXT NOT NULL DEFAULT 'primary_support',
  bound_by TEXT NOT NULL,
  bound_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, id),
  UNIQUE (tenant_id, decision_id, evidence_id),
  FOREIGN KEY (tenant_id, decision_id) REFERENCES decision(tenant_id, id),
  FOREIGN KEY (tenant_id, evidence_id) REFERENCES evidence_artifact(tenant_id, id)
);

INSERT INTO investigation(tenant_id, id, title, question, owner, created_by, created_at, updated_at)
VALUES ('tenant_alpha', 'inv-v0', 'Legacy investigation', 'Why?', 'owner', 'user', '2026-01-01', '2026-01-01');

INSERT INTO evidence_artifact(tenant_id, id, investigation_id, metric_id, dataset_id, canonical_digest, created_by, created_at)
VALUES ('tenant_alpha', 'ev-v0', 'inv-v0', 'm', 'ds', 'digest', 'user', '2026-01-01');

INSERT INTO decision(id, tenant_id, title, brief_json, created_by, created_at, updated_at)
VALUES ('dec-v0', 'tenant_alpha', 'Legacy decision', '{}', 'user', '2026-01-01', '2026-01-01');

INSERT INTO decision_evidence_binding(tenant_id, id, decision_id, evidence_id, bound_by, bound_at)
VALUES ('tenant_alpha', 'bind-v0', 'dec-v0', 'ev-v0', 'user', '2026-01-01');
"""


def _connect(path: Path, foreign_keys: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'}")
    return conn


def _db_version(conn: sqlite3.Connection) -> int:
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if not has_table:
        return 0
    return int(conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0)


def _build_minimal_v0(path: Path) -> Path:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_V0_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return path


def _copy_live_v0_or_build(tmp_path: Path) -> tuple[Path, bool]:
    """Return (path, copied_from_live). Falls back to a hand-built v0 fixture."""
    target = tmp_path / "v0.sqlite3"
    if LIVE_DB.exists():
        src = sqlite3.connect(LIVE_DB)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
        conn = _connect(target)
        try:
            is_v0 = _db_version(conn) == 0
        finally:
            conn.close()
        if is_v0:
            return target, True
    return _build_minimal_v0(target), False


def test_fresh_database_applies_both_migrations(tmp_path):
    conn = _connect(tmp_path / "fresh.sqlite3")
    try:
        assert apply_pending(conn) == [1, 2, 3]
        assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 3
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_existing_v0_database_upgrades_without_data_loss(tmp_path):
    path, _copied = _copy_live_v0_or_build(tmp_path)
    conn = _connect(path)
    try:
        decisions_before = conn.execute("SELECT COUNT(*) FROM decision").fetchone()[0]
        bindings_before = conn.execute("SELECT COUNT(*) FROM decision_evidence_binding").fetchone()[0]
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("PRAGMA foreign_key_check").fetchall()

        assert apply_pending(conn) == [1, 2, 3]

        assert conn.execute("SELECT COUNT(*) FROM decision").fetchone()[0] == decisions_before
        assert conn.execute("SELECT COUNT(*) FROM decision_evidence_binding").fetchone()[0] == bindings_before
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 3
    finally:
        conn.close()


def test_database_newer_than_code_is_refused(tmp_path):
    conn = _connect(tmp_path / "future.sqlite3")
    try:
        apply_pending(conn)
        conn.execute(
            "INSERT INTO schema_version(version, name, applied_at) VALUES (?, ?, ?)",
            (CODE_MAX + 1, "from_the_future", "2026-01-01"),
        )
        conn.commit()
        with pytest.raises(RuntimeError) as raised:
            apply_pending(conn)
        message = str(raised.value)
        assert str(CODE_MAX + 1) in message
        assert str(CODE_MAX) in message
    finally:
        conn.close()


def test_rerun_on_current_database_is_a_no_op(tmp_path):
    conn = _connect(tmp_path / "current.sqlite3")
    try:
        assert apply_pending(conn) == [1, 2, 3]
        versions_before = conn.execute("SELECT * FROM schema_version ORDER BY version").fetchall()
        schema_before = conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()

        assert apply_pending(conn) == []

        assert conn.execute("SELECT * FROM schema_version ORDER BY version").fetchall() == versions_before
        assert (
            conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall()
            == schema_before
        )
    finally:
        conn.close()


def test_composite_foreign_key_is_enforced_after_migration(tmp_path):
    conn = _connect(tmp_path / "fk.sqlite3")
    try:
        assert apply_pending(conn) == [1, 2, 3]
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

        conn.execute(
            "INSERT INTO investigation(tenant_id, id, title, question, owner, created_by, created_at, updated_at) "
            "VALUES ('tenant_alpha', 'inv-live', 'Inv', 'Q', 'owner', 'user', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO evidence_artifact("
            "tenant_id, id, investigation_id, metric_id, dataset_id, canonical_digest, created_by, created_at"
            ") VALUES ('tenant_alpha', 'ev-live', 'inv-live', 'm', 'ds', 'digest', 'user', '2026-01-01')"
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO decision_evidence_binding("
                "tenant_id, id, decision_id, evidence_id, bound_by, bound_at"
                ") VALUES ('tenant_alpha', 'bind-bad', 'missing-decision', 'ev-live', 'user', '2026-01-01')"
            )

        conn.execute(
            "INSERT INTO decision(tenant_id, id, title, brief_json, created_by, created_at, updated_at) "
            "VALUES ('tenant_alpha', 'dec-live', 'Decision', '{}', 'user', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO decision_evidence_binding("
            "tenant_id, id, decision_id, evidence_id, bound_by, bound_at"
            ") VALUES ('tenant_alpha', 'bind-good', 'dec-live', 'ev-live', 'user', '2026-01-01')"
        )
        conn.commit()
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()
