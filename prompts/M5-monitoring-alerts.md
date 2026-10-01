You are building M5 — Monitoring, Incidents, and Alerts for **DecisionOS** at C:\Users\AMD\Desktop\DecisionOS.

## SPEC REFERENCE (§14 — Monitoring, incidents, and alerts)

### 14.1 Separate data incidents from business signals
A failed extract and a genuine reduction in activity are different events. Store health by dataset revision and by check; derive impact through the dependency graph. For invalid inputs, suspend unsupported calculations and show the last valid result as stale. An `unknown` health state opens investigation.

### 14.2 Contextual detection
Fit the baseline using information available before the scored observation. Candidate methods: seasonal naive ranges, robust calendar regression, residual detection, change-point analysis. For each alert record: observed value, expected value/interval, scoring method, training window, drivers, threshold, minimum effect size, persistence requirement, and data-health state. Handle constant baselines with explicit change thresholds. Control false discoveries across many metrics/segments.

### 14.3 Alert state
Three separate records:
- **Condition state**: normal, pending, active, recovered.
- **Episode workflow**: open, acknowledged, investigating, resolved, dismissed.
- **Delivery/suppression**: queued, sent, failed, suppressed with reason and expiry.
Dedupe uses tenant + rule version + segment + stable episode identity (not firing timestamp). Notifications have retry. Each enabled rule has owner, escalation route, resolution guidance.

## CURRENT STATE
- **Python API** on :8100 with FastAPI, polars, pydantic, uvicorn, SQLite store
- **Nuxt frontend** on :3000 with Vue 3, composables/api.ts, full types
- **122 tests passing** (core + forecasting + workflow + scenarios + simulation + decision register)
- Database at services/analytics/dev.db (SQLite)
- Uses pattern: store.py SCHEMA constant for DDL, evidence + audit for every action, /v1 prefix, ctx() for tenant/user

## EXISTING CODEBASE PATTERNS (MIMIC THESE)
- New modules: services/analytics/decisionos_analytics/monitoring.py
- API routes added inside `def _register(store, objects)` closure in api.py
- Routes use `@app.post("/v1/monitoring/...")` with `ctx(x_tenant, x_user)` for auth
- Evidence saved via `store.save_evidence(tenant, "monitoring_xxx", {...})`
- Audit via `store.audit(tenant, user, "monitoring.xxx", target, "result", {...})`
- Store schema extended via SQL DDL in the SCHEMA constant of store.py
- Frontend pages at apps/web/pages/monitoring.vue (Nuxt 3)
- Frontend types in apps/web/shared/types.ts

## YOUR TASK — Execute ALL of the following:

### 1. Create services/analytics/decisionos_analytics/monitoring.py
A module implementing context detection and alert lifecycle:

```python
class DataHealth:
    """Health per dataset revision.
    - freshness: time since last revision
    - status: 'healthy' | 'stale' | 'suspended' | 'unknown'
    - dependency impact computed from upstream dataset health
    """
    @staticmethod
    def check(tenant: str, dataset_id: str, store: Store) -> dict

class ContextualDetector:
    """Anomaly detection on a metric series.
    
    Methods (from §14.2):
    - seasonal_naive: seasonal naive range ± k*MAD
    - residual_detection: residual from expected vs observed
    - change_point: detect level shifts via CUSUM or similar
    """
    @staticmethod
    def seasonal_naive_range(series: list[float], season_length: int, k: float = 3) -> tuple[float, float]
    
    @staticmethod
    def detect_anomalies(series: list[float], method: str = "seasonal_naive", 
                         season_length: int = 7, threshold: float = 3.0,
                         min_effect_size: float = 0.01) -> list[dict]
    # Each anomaly: {"index", "observed", "expected_lower", "expected_upper", "method", "effect_size", "persistent_count"}

class AlertEngine:
    """Evaluate rules against metric queries, fire alerts with deduplication."""
    
    @staticmethod
    def evaluate_rules(tenant: str, store: Store, conn) -> list[dict]
    # Load all enabled rules, query the metric data, run detection, fire if threshold crossed
    # Dedupe by (tenant, rule_id, episode_identity) — NOT by timestamp
    
    @staticmethod
    def fire_alert(tenant: str, rule_id: str, anomaly: dict, store: Store, conn) -> dict
    # Create/update condition_state, create alert_episode if new episode
    # Condition: normal→pending→active→recovered
    # Episode: open→acknowledged→investigating→resolved→dismissed

class AlertLifecycle:
    """CRUD for alert rules, episodes, condition states."""
    @staticmethod
    def create_rule(tenant: str, rule: dict, user: str, store: Store) -> dict
    @staticmethod
    def list_rules(tenant: str, store: Store) -> list[dict]
    @staticmethod
    def update_rule(tenant: str, rule_id: str, updates: dict, user: str, store: Store) -> dict
    @staticmethod
    def list_episodes(tenant: str, store: Store, status: str | None = None) -> list[dict]
    @staticmethod
    def transition_episode(tenant: str, episode_id: str, new_status: str, user: str, store: Store) -> dict
    @staticmethod
    def list_condition_states(tenant: str, store: Store) -> list[dict]
```

### 2. Add SQLite DDL to store.py SCHEMA
Add these tables to the existing SCHEMA string:
```sql
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
  episode_identity TEXT NOT NULL,  -- stable identity for dedup: method+segment
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
  status TEXT NOT NULL DEFAULT 'queued',  -- queued, sent, failed, suppressed
  suppressed_reason TEXT,
  retry_count INTEGER DEFAULT 0,
  last_attempt TEXT,
  PRIMARY KEY (tenant_id, episode_id)
);
```

### 3. Add API endpoints to api.py (in the _register function)

```
GET  /v1/monitoring/health/{dataset_id}
     → {dataset_id, freshness_hours, revision_count, latest_revision, 
        last_ingested_at, status: 'healthy'|'stale'|'suspended'|'unknown', 
        revision_history: [{revision, created_at, object_count}]}

POST /v1/monitoring/rules
     Body: {name, dataset_id, metric_id, method, season_length?, threshold?, 
            min_effect_size?, persistence?, owner, escalation?, runbook?}
     → {status: 'created', rule: {...}}

GET  /v1/monitoring/rules
     Query: enabled_only? (boolean)
     → {rules: [...]}

PUT  /v1/monitoring/rules/{rule_id}
     Body: partial rule updates (name, threshold, owner, escalation, enabled, etc)
     → {status: 'updated', rule: {...}}

POST /v1/monitoring/evaluate
     Body: {dataset_ids?: [str], rule_ids?: [str]}
     → {status: 'answered', evaluated: int, anomalies_fired: int, episodes: [{...}]}

GET  /v1/monitoring/conditions
     → {conditions: [{id, rule_id, rule_name, condition, started_at, recovered_at}]}

GET  /v1/monitoring/episodes
     Query: status? (open|acknowledged|investigating|resolved|dismissed), limit?
     → {episodes: [...]}

PUT  /v1/monitoring/episodes/{episode_id}/status
     Body: {status, notes?}
     → {status: 'updated', episode: {...}, condition: {...}}
```

### 4. Create monitoring.vue frontend page at apps/web/pages/monitoring.vue
- **Nav link** added (add to app.vue or layout)
- **Tabs**: Data Health | Alert Rules | Active Episodes | History
- **Data Health tab**: table of datasets with freshness, status badge (green/yellow/red/gray), last revision time
- **Alert Rules tab**: list of rules with toggle enable/disable, edit button, create new button (modal/inline form)
- **Active Episodes tab**: current open/acknowledged/investigating episodes with status badge, transition buttons (acknowledge→investigate→resolve), observed vs expected display
- **History tab**: resolved/dismissed episodes with resolution info
- Use existing Card/Badge/Muted CSS patterns from the app design
- Follow the same pattern as scenarios.vue and workflow.vue

### 5. Add TypeScript types to shared/types.ts
Types for:
```
MonitoringHealthResponse, AlertRule, AlertRuleCreateRequest, AlertRuleListResponse,
ConditionState, AlertEpisode, AlertEpisodeListResponse, AlertEvaluateResponse,
AlertStatusTransitionRequest
```

### 6. Create comprehensive tests at services/analytics/tests/test_monitoring.py
Minimum 10 tests covering:
- DataHealth check returns correct status for datasets with/without revisions
- DataHealth shows 'unknown' for non-existent dataset
- Create alert rule via AlertLifecycle
- List alert rules
- Update alert rule (threshold, enabled)
- Seasonal naive detector produces valid ranges
- Detect anomalies on simple constant series (zero MAD edge case)
- Detect anomalies on seasonal series with known outlier
- AlertEngine evaluates rules and fires alerts on anomalies
- Alert episode lifecycle: open→acknowledged→investigating→resolved
- Condition lifecycle: normal→active→recovered
- Deduplication: same anomaly doesn't create duplicate episodes
- API integration tests using TestClient for each endpoint
- Edge case: constant baseline with sudden jump (must detect)

### 7. Verify nothing breaks
After all changes, run:
```bash
PYTHONPATH="" ./services/analytics/.venv/Scripts/python -m pytest services/analytics/tests/ -v
```
All 122+ existing tests must still pass, plus the new monitoring tests.

## CONSTRAINTS
- Stay ONLY under C:\Users\AMD\Desktop\DecisionOS
- Don't break existing tests (122 passing currently)
- Don't remove or rename existing functions/modules
- New endpoints use /v1 prefix with X-Tenant/X-User headers
- Use PYTHONPATH="" when running tests
- Follow the exact patterns from existing M2/M3/M4 code (same store access, evidence, audit style)