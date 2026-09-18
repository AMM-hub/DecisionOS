"""SQLite-backed control-plane store for the local development worker service.

Mirrors the composite-tenant integrity pattern from the Laravel migrations
(spec §22.2): every tenant-scoped table carries tenant_id in its primary key
and every query is tenant-filtered. Production authority is PostgreSQL via the
Laravel API; this store exists so the pipeline is runnable and testable today.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tenant (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace (
  tenant_id TEXT NOT NULL REFERENCES tenant(id),
  id TEXT NOT NULL,
  name TEXT NOT NULL,
  PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS member (
  tenant_id TEXT NOT NULL REFERENCES tenant(id),
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,
  PRIMARY KEY (tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS upload (
  tenant_id TEXT NOT NULL REFERENCES tenant(id),
  id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  created_by TEXT NOT NULL,
  filename TEXT NOT NULL,
  quarantine_key TEXT NOT NULL,
  sha256 TEXT,
  status TEXT NOT NULL,           -- initiated|quarantined|scanned|rejected|parsed|cancelled
  scan_result TEXT,
  parse_preview TEXT,
  dataset_id TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, workspace_id) REFERENCES workspace(tenant_id, id)
);

CREATE TABLE IF NOT EXISTS dataset (
  tenant_id TEXT NOT NULL REFERENCES tenant(id),
  id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  name TEXT NOT NULL,
  published_revision INTEGER,
  grain_confirmed_at TEXT,
  grain_key TEXT,                 -- json list
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, id),
  UNIQUE (tenant_id, workspace_id, name),
  FOREIGN KEY (tenant_id, workspace_id) REFERENCES workspace(tenant_id, id)
);

CREATE TABLE IF NOT EXISTS dataset_revision (
  tenant_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  state TEXT NOT NULL,            -- staged|validating|validated|failed|published
  manifest TEXT NOT NULL,         -- json: objects+hashes, schema, row counts, checkpoint
  row_count INTEGER NOT NULL,
  rejected_row_count INTEGER NOT NULL DEFAULT 0,
  lease_owner TEXT,
  lease_expires_at TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, dataset_id, revision),
  FOREIGN KEY (tenant_id, dataset_id) REFERENCES dataset(tenant_id, id)
);

CREATE TABLE IF NOT EXISTS definition (
  tenant_id TEXT NOT NULL REFERENCES tenant(id),
  id TEXT NOT NULL,
  kind TEXT NOT NULL,
  created_by TEXT NOT NULL,
  PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS definition_version (
  tenant_id TEXT NOT NULL,
  definition_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  content TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, definition_id, version),
  FOREIGN KEY (tenant_id, definition_id) REFERENCES definition(tenant_id, id)
);

CREATE TABLE IF NOT EXISTS definition_publication (
  tenant_id TEXT NOT NULL,
  definition_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  semantic_release_id TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  published_at TEXT NOT NULL,
  approved_by TEXT NOT NULL,
  change_reason TEXT NOT NULL,
  PRIMARY KEY (tenant_id, definition_id, version, effective_from),
  FOREIGN KEY (tenant_id, definition_id, version) REFERENCES definition_version(tenant_id, definition_id, version)
);

CREATE TABLE IF NOT EXISTS outbox_event (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  aggregate_version INTEGER NOT NULL,
  occurred_at TEXT NOT NULL,
  payload TEXT NOT NULL,
  dispatched_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT NOT NULL,
  result TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  context TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
  tenant_id TEXT NOT NULL,
  id TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS forecast_model (
  tenant_id TEXT NOT NULL REFERENCES tenant(id),
  id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  metric_id TEXT NOT NULL,
  spec TEXT NOT NULL,             -- json model_spec (series embedded; predict refits)
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, id)
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    def __init__(self, path: Path | str) -> None:
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # -- helpers ---------------------------------------------------------
    def audit(self, tenant_id: str, actor: str, action: str, target: str, result: str, context: dict | None = None) -> None:
        self.conn.execute(
            "INSERT INTO audit_event(tenant_id, actor, action, target, result, occurred_at, context) VALUES (?,?,?,?,?,?,?)",
            (tenant_id, actor, action, target, result, now_iso(), json.dumps(context or {})),
        )
        self.conn.commit()

    def emit(self, tenant_id: str, event_type: str, aggregate_id: str, aggregate_version: int, payload: dict) -> str:
        event_id = new_id()
        self.conn.execute(
            "INSERT INTO outbox_event(event_id, event_type, schema_version, tenant_id, aggregate_id, aggregate_version, occurred_at, payload) VALUES (?,?,?,?,?,?,?,?)",
            (event_id, event_type, "1.0", tenant_id, aggregate_id, aggregate_version, now_iso(), json.dumps(payload)),
        )
        return event_id

    def save_evidence(self, tenant_id: str, kind: str, payload: dict) -> str:
        eid = new_id()
        self.conn.execute(
            "INSERT INTO evidence(tenant_id, id, kind, payload, created_at) VALUES (?,?,?,?,?)",
            (tenant_id, eid, kind, json.dumps(payload), now_iso()),
        )
        self.conn.commit()
        return f"evidence-{eid[:8]}"

    def close(self) -> None:
        self.conn.close()
