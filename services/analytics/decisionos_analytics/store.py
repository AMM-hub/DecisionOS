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

INSERT OR IGNORE INTO tenant VALUES ('tenant_alpha', 'Northline Telecom (synthetic)');
INSERT OR IGNORE INTO tenant VALUES ('tenant_beta', 'Harbor Retail Bank (synthetic)');

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

CREATE TABLE IF NOT EXISTS alert_rule (
  tenant_id TEXT NOT NULL,
  id TEXT NOT NULL,
  name TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  metric_id TEXT NOT NULL,
  method TEXT NOT NULL DEFAULT 'seasonal_naive',
  season_length INTEGER NOT NULL DEFAULT 7,
  threshold REAL NOT NULL DEFAULT 3.0,
  min_effect_size REAL NOT NULL DEFAULT 0.01,
  persistence INTEGER NOT NULL DEFAULT 1,
  owner TEXT NOT NULL,
  escalation TEXT DEFAULT '',
  runbook TEXT DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS condition_state (
  tenant_id TEXT NOT NULL,
  id TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  condition TEXT NOT NULL DEFAULT 'normal',
  started_at TEXT,
  recovered_at TEXT,
  PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS alert_episode (
  tenant_id TEXT NOT NULL,
  id TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  episode_identity TEXT NOT NULL,
  condition_id TEXT NOT NULL,
  workflow_status TEXT NOT NULL DEFAULT 'open',
  observed_value REAL,
  expected_lower REAL,
  expected_upper REAL,
  scoring_method TEXT,
  training_window TEXT,
  effect_size REAL,
  persistence_count INTEGER DEFAULT 0,
  started_at TEXT NOT NULL,
  resolved_at TEXT,
  acknowledged_at TEXT,
  acknowledged_by TEXT,
  resolution_notes TEXT,
  PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS alert_delivery (
  tenant_id TEXT NOT NULL,
  episode_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  suppressed_reason TEXT,
  retry_count INTEGER DEFAULT 0,
  last_attempt TEXT,
  PRIMARY KEY (tenant_id, episode_id)
);

CREATE TABLE IF NOT EXISTS decision (
  tenant_id TEXT NOT NULL REFERENCES tenant(id),
  id TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  brief_json TEXT NOT NULL,
  counterevidence_json TEXT NOT NULL DEFAULT '[]',
  amendments_json TEXT NOT NULL DEFAULT '[]',
  outcome_json TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS investigation (
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

CREATE TABLE IF NOT EXISTS evidence_artifact (
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

CREATE TABLE IF NOT EXISTS investigation_claim (
  tenant_id TEXT NOT NULL REFERENCES tenant(id),
  id TEXT NOT NULL,
  investigation_id TEXT NOT NULL,
  evidence_id TEXT,
  statement TEXT NOT NULL,
  evidence_type TEXT NOT NULL DEFAULT 'observed',
  support_status TEXT NOT NULL DEFAULT 'supporting',
  quality_flags_json TEXT NOT NULL DEFAULT '[]',
  structured_fact_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, investigation_id) REFERENCES investigation(tenant_id, id),
  FOREIGN KEY (tenant_id, evidence_id) REFERENCES evidence_artifact(tenant_id, id)
);

CREATE TABLE IF NOT EXISTS decision_evidence_binding (
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

CREATE TABLE IF NOT EXISTS predictive_target (
  tenant_id TEXT NOT NULL REFERENCES tenant(id),
  id TEXT NOT NULL,
  name TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  outcome_definition_json TEXT NOT NULL,
  observation_time_semantics TEXT NOT NULL DEFAULT 'as_of',
  outcome_window TEXT NOT NULL,
  eligible_population TEXT NOT NULL DEFAULT 'all',
  deadline_semantics TEXT NOT NULL,
  time_basis TEXT NOT NULL DEFAULT 'calendar_utc',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS predictive_model (
  tenant_id TEXT NOT NULL REFERENCES tenant(id),
  id TEXT NOT NULL,
  target_id TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  model_kind TEXT NOT NULL DEFAULT 'classification_risk',
  algorithm TEXT NOT NULL,
  feature_contract_json TEXT NOT NULL,
  training_dataset_revision INTEGER NOT NULL,
  training_time_range_json TEXT NOT NULL,
  evaluation_time_range_json TEXT NOT NULL,
  hyperparameters_json TEXT NOT NULL DEFAULT '{}',
  calibration_method TEXT NOT NULL DEFAULT 'platt',
  threshold_policy_json TEXT NOT NULL DEFAULT '{}',
  metrics_json TEXT NOT NULL DEFAULT '{}',
  checksum TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  intended_use TEXT NOT NULL DEFAULT '',
  excluded_uses TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  approved_by TEXT,
  approved_at TEXT,
  activated_at TEXT,
  superseded_by TEXT,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, target_id) REFERENCES predictive_target(tenant_id, id)
);

CREATE TABLE IF NOT EXISTS predictive_prediction (
  tenant_id TEXT NOT NULL REFERENCES tenant(id),
  id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  model_version INTEGER NOT NULL,
  target_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  observation_time TEXT NOT NULL,
  score REAL NOT NULL,
  risk_tier TEXT NOT NULL,
  threshold_used REAL NOT NULL,
  outcome_window TEXT NOT NULL,
  source_dataset_revision INTEGER NOT NULL,
  feature_snapshot_json TEXT NOT NULL DEFAULT '{}',
  suitability_status TEXT NOT NULL DEFAULT 'suitable',
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, model_id) REFERENCES predictive_model(tenant_id, id)
);

CREATE TABLE IF NOT EXISTS pilot (
  tenant_id TEXT NOT NULL REFERENCES tenant(id),
  id TEXT NOT NULL,
  name TEXT NOT NULL,
  domain TEXT NOT NULL DEFAULT 'support_ticket_operations',
  owner TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  dataset_id TEXT,
  dataset_revision INTEGER,
  timezone TEXT NOT NULL DEFAULT 'UTC',
  time_basis TEXT NOT NULL DEFAULT 'calendar_utc',
  started_at TEXT,
  target_end_at TEXT,
  config_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
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
