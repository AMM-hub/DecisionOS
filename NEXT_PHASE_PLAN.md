# DecisionOS — Next Product Phase Plan (Corrected Architecture Freeze)

## 1. True Accepted Baseline Status

- **Accepted Baseline Commit**: `4c6576d` (`fix(release): complete round 2 remediation and regression gates`)
- **Git Branch**: `main`
- **Working Tree Status**: CLEAN (baseline frozen)
- **Authoritative Verification Evidence**:
  - **Backend Test Suite**: `207 passed, 0 failures`
  - **Measured Pytest Coverage**: `93%` total statement coverage across all 38 test & engine modules
  - **Frontend Typecheck (`vue-tsc --noEmit`)**: PASS (0 errors)
  - **Frontend Production Build (`nuxt build`)**: PASS (0 errors)
  - **Security Regression Matrix**:
    - `test_tenant_security.py`: Tracked & Verified (0 cross-tenant leaks)
    - `test_structural_authorization.py`: Tracked & Verified
    - `test_malformed_requests.py`: Tracked & Verified (400 Bad Request error handling)
    - `test_solver_error_classification.py`: Tracked & Verified (200 Optimal / 200 Infeasible / 422 Malformed / 500 Internal error mappings)
    - `test_scenario_contract.py`: Tracked & Verified
    - `test_security_input_matrix.py`: Tracked & Verified

No source code, database migrations, schemas, or feature endpoints were modified during this planning task.

---

## 2. Corrected Implementation Inventory & Module Ownership

An empirical audit of `services/analytics/decisionos_analytics/` and `apps/web/` yields the following authoritative module responsibilities:

| Module | Actual Current Responsibility | Source Evidence |
| :--- | :--- | :--- |
| `api.py` | FastAPI app creation, `/v1/...` route registration, request error handlers (`400`, `401`, `404`, `422`), header-based auth context (`ctx(x_tenant, x_user)`), CORS, audit log triggers. | `api.py` (L19, L47-110, L116-1032) |
| `store.py` | SQLite control DB manager (`Store`), schema creation, transaction wrapper, audit trail (`audit_log`), UUID generation (`new_id()`), timestamping (`now_iso()`). | `store.py` (L1-150) |
| `register.py` | Semantic Metric Registry (`MetricRegister`), metric formula compilation, and **Decision Register Core** (`DECISION_SCHEMA`, 12-state lifecycle `DecisionStatus`, `DecisionBrief`, `CounterevidenceCheck`, `DecisionAmendment`, `OutcomeRecord`). | `register.py` (L36-128, L139-250) |
| `execution.py` | Metric plan compilation (`compile_plan`) and typed metric query execution engine (`execute`) over Polars DataFrames with business timezone windowing. | `execution.py` (L1-147) |
| `semantics.py` | Pydantic data models for semantic metrics (`MetricDefinitionContent`), queries (`MetricQueryRequest`), predicates, aggregations, directionality. | `semantics.py` (L1-100) |
| `pipeline.py` | Ingestion pipeline: upload quarantine, parsing, Parquet conversion, dataset revision publication (`publish_revision`), expiration sweeping. | `pipeline.py` (L1-200) |
| `parsing.py` | File parsers (CSV, JSON, Parquet), column auto-detection, schema profiling. | `parsing.py` (L1-150) |
| `grain.py` | Grain proof evaluation engine, candidate grain discovery, uniqueness checks. | `grain.py` (L1-100) |
| `monitoring.py` | Monitoring & Alert Engine: health rules (`HealthRule`), threshold evaluation, episode creation (`Episode`), health score aggregation. | `monitoring.py` (L1-200) |
| `workflow.py` | Process Mining Engine: event log parsing, variant analysis, throughput time calculation, bottleneck detection, conformance checking. | `workflow.py` (L1-200) |
| `optimization.py` | Scenario Optimization Engine: PuLP linear programming formulation for capacity allocation, solver status mapping, IIS diagnostic relaxation. | `optimization.py` (L1-150) |
| `forecasting.py` | Time-series forecasting engine using `StatsForecast` (`AutoARIMA`, `AutoETS`, `AutoTheta`), dataset suitability checks, confidence interval bands (`p10/p50/p90`). | `forecasting.py` (L1-150) |
| `objectstore.py` | Local Object Store (`LocalObjectStore`) managing Parquet files under `data_dir/objects/`. | `objectstore.py` (L1-80) |
| `bilingual.py` | Bilingual translation strings, localization dictionary helper (`en`/`ar`). | `bilingual.py` (L1-100) |
| `simulation.py` | Synthetic data generator & Difference-in-Differences causal evaluation stub. | `simulation.py` (L1-100) |

### Corrected Architectural Misconceptions
1. **`auth.py` DOES NOT EXIST**: Authentication is handled inline inside `api.py` via `ctx(x_tenant, x_user)` checking `DEMO_TENANTS` and `DEMO_USERS` headers (`X-Tenant` / `X-Tenant-ID` and `X-User`). No Bearer token or OAuth JWT service exists.
2. **`execution.py` DOES NOT OWN DECISIONS**: `execution.py` is purely for metric query plan compilation and execution over Polars. Decision Briefs and the Decision Register lifecycle are owned by `register.py` and served via `@app.*/v1/decisions` in `api.py`.
3. **Prophet & PuLP Dependencies**: `forecasting.py` uses `statsforecast` (not `prophet`). `optimization.py` uses `pulp` (installed python package) for linear programming formulations.
4. **API Namespace**: All endpoints strictly use the `/v1/...` prefix convention (e.g. `/v1/decisions`), NOT `/api/v1/...`.

---

## 3. Strict Delivery Stage Assessment (Spec §30.2)

| Stage | Spec Required Outcome & Gate | Actual Repository Evidence | Status |
| :--- | :--- | :--- | :--- |
| **D0: Validate and design** | Real decision/problem, data sample, initial golden questions, named buyer/owner, pilot scope. | Synthetic sample data (Northline Telecom / Harbor Retail Bank), domain schemas, and pilot scopes exist in test fixtures. No live customer buyer attached. | **PARTIAL** *(Complete for synthetic demo scope)* |
| **D1: Trusted analytical core** | Secure workspace, ingestion/revisions, semantic definitions, typed queries, evidence, bilingual dashboards. | Parquet upload pipeline, dataset revisions, DuckDB/Polars typed query engine, and bilingual UI exist. Visual metric catalog builder UI and evidence snapshotting are missing. | **PARTIAL** |
| **D2: Operational loop** | Workflow metrics, data incidents, business alerts, investigations, decision register/reviews. | Workflow metrics (`workflow.py`), monitoring alerts (`monitoring.py`), and decision register structure (`register.py`) exist. **Investigation workspace and evidence snapshot linking are missing.** | **PARTIAL** |
| **D3: Predictive capability** | Separately validated time-series, classification, survival, and backlog modules. | Time-series forecasting (`forecasting.py` via `StatsForecast`) and process bottleneck detection exist. Risk classification models and survival analysis are not started. | **PARTIAL** |
| **D4: Scenario and evaluation** | Scenario templates, valid optimization/simulation, decision briefs, study evaluation. | PuLP capacity optimization solver (`optimization.py`) and decision brief models (`register.py`) exist. Simulation & causal study evaluation are scaffolded stubs. | **PARTIAL** |
| **D5: Enterprise expansion** | Contract-driven integrations, SAML/SSO, provisioning, advanced scale. | Multi-tenant header validation works. SAML/SSO, vector search, and external action dispatchers not started. | **NOT STARTED** |

---

## 4. Next Phase Selection & Prerequisite Validation

**RECOMMENDED NEXT PHASE**: **"Evidence, Investigation & Decision Loop" (Phase D2 Completion)**

### Prerequisite Chain Check (Spec §30.3 W01–W16):
- **W04 (Identity & Tenancy)**: `COMPLETE` (Tenant isolation & header context validated).
- **W05 (Storage & Revisions)**: `COMPLETE` (Parquet storage & revision publication working).
- **W07 (Dataset Readiness)**: `COMPLETE` (Grain proof & schema inference working).
- **W08 (Definitions & Releases)**: `MOSTLY COMPLETE` (Semantic definitions & metric registry working).
- **W09 (Typed Query Execution)**: `COMPLETE` (`execution.py` compiled plans & windowing working).
- **W10 (Findings, Claims & Evidence)**: **MISSING — PRIMARY TARGET OF THIS PHASE**.
- **W14 (Workflow)** & **W15 (Monitoring)**: `COMPLETE` (Episode alerts & process mining working).
- **W16 (Decision Register)**: `PARTIAL` (Backend state machine in `register.py` working; evidence snapshot binding missing).

---

## 5. Specification-Grade Evidence & Provenance Model

Evidence in DecisionOS is **NOT** a simple Parquet file with a SHA-256 checksum. In accordance with Spec §10 & §16, an **Evidence Artifact** is a rich, auditable reproduction record.

### Evidence Artifact Schema
Every captured evidence record must contain:
1. `artifact_id` (str, PK)
2. `parent_artifact_ids` (list[str] - for lineage & correction tracking)
3. `tenant_id` & `workspace_id` (str, indexed)
4. `created_by` & `service_identity` (str)
5. `created_at` (ISO timestamp)
6. `evidence_type`: `observed` | `estimated` | `simulated` | `causal_estimate` | `hypothesis`
7. `support_status`: `supporting` | `counter` | `neutral` | `unverified`
8. `quality_flags`: list of flags (e.g. `provisional_definition`, `stale_data`, `sampled`, `inferred_event_time`, `partial_coverage`, `approximate`)
9. `resolved_plan`: JSON of resolved analytical query plan (`MetricQueryRequest` + `compile_plan` output)
10. `metric_id` & `definition_version` (int)
11. `dataset_id` & `dataset_revision` (int)
12. `query_params`: window, dimensions, filters
13. `period`: `{ start: str, end: str, timezone: str }`
14. `unit` & `segment_dimensions`
15. `canonical_digest`: SHA-256 hash of canonical normalized JSON or Parquet content
16. `exactness_class`: `exact` | `approximate` | `bounded_estimate`
17. `reproducibility_status`: `reproducible` | `stale_source` | `archived` | `non_reproducible`

### Logical Immutability Strategy
- **No filesystem permission hacks (`chmod 0444`)**: Immutability is enforced via storage abstraction.
- **Append-only & Versioned**: Evidence artifacts are read-only upon creation. No `UPDATE` or `PUT` endpoint exists for snapshot payloads.
- **Corrections**: Correcting or updating evidence creates a new `artifact_id` pointing to `parent_artifact_ids`.
- **Tenant Scope**: Evidence retrieval validates tenant authorization and re-verifies `canonical_digest` on read.

---

## 6. Structured Claims & Fact Model

Investigation Claims are **not text notes**. A Claim is a structured domain object backed by verifiable facts:

### Claim Model
- `claim_id` (str, PK)
- `investigation_id` (str, FK)
- `hypothesis` (str)
- `evidence_type`: `observed` | `estimated` | `simulated` | `causal_estimate` | `hypothesis`
- `support_status`: `supporting` | `counter` | `neutral` | `unverified`
- `quality_flags`: list of quality flag strings
- `structured_fact`: `{ metric_id: str, value: float|int|str, unit: str, segment: dict, period: str, comparison: str|None, lineage: dict }`
- `linked_evidence_id` (str, FK to `evidence_artifact`, optional)

---

## 7. Investigation Workspace Architecture

An `Investigation` preserves the analytical state and audit trail of an incident review:

### Investigation Schema
- `id` (str, PK)
- `tenant_id` (str, FK, indexed)
- `title` (str)
- `question` (str)
- `source_type`: `monitoring_episode` | `workflow_bottleneck` | `ad_hoc`
- `source_id` (str, optional)
- `status`: `open` | `in_progress` | `resolved` | `closed`
- `owner` (str)
- `analytical_state_json` (JSON summary of active queries and findings)
- `alternative_explanations_json` (list of alternative hypotheses)
- `created_by` & `created_at` & `updated_at`

### Monitoring & Workflow Episode Linkage
- **Idempotent Launch**: `POST /v1/monitoring/episodes/{episode_id}/investigate` checks if an investigation already exists for `(tenant_id, 'monitoring_episode', episode_id)`. If present, returns existing investigation (`200 OK`); otherwise creates a new investigation (`201 Created`).
- **Domain Generality**: Preserves generic source linking (`source_type`, `source_id`) without hardcoding specific vertical domains.

---

## 8. Decision Lifecycle & Decision Register Integration

Uses the existing 12-state machine in `register.py` (Spec §19.2):

```
draft → proposed → accepted → implementation_pending → active → review_due → evaluated → closed
(Terminal / Alternate: rejected, deferred, abandoned, superseded)
```

- **Frozen Context**: Marking a decision `accepted` freezes its linked evidence and brief context.
- **Amendments**: Subsequent edits create an append-only `DecisionAmendment` record (`version`, `author`, `reason`, `scope`, `previous_version`, `changes`).
- **Counterevidence Checks**: Evaluates checks across 4 states (`detected`, `not_detected`, `not_testable`, `not_run`).

---

## 9. SQLite Data Model Changes

All new tables enforce composite tenant integrity with strict `tenant_id` foreign keys and indexes:

```sql
CREATE TABLE IF NOT EXISTS investigation (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    title TEXT NOT NULL,
    question TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    owner TEXT NOT NULL,
    analytical_state_json TEXT NOT NULL DEFAULT '{}',
    alternative_explanations_json TEXT NOT NULL DEFAULT '[]',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenant(id)
);
CREATE INDEX IF NOT EXISTS idx_investigation_tenant ON investigation(tenant_id, status);

CREATE TABLE IF NOT EXISTS evidence_artifact (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    investigation_id TEXT NOT NULL,
    parent_artifact_ids_json TEXT NOT NULL DEFAULT '[]',
    evidence_type TEXT NOT NULL DEFAULT 'observed',
    support_status TEXT NOT NULL DEFAULT 'supporting',
    quality_flags_json TEXT NOT NULL DEFAULT '[]',
    metric_id TEXT NOT NULL,
    definition_version INTEGER NOT NULL,
    dataset_id TEXT NOT NULL,
    dataset_revision INTEGER NOT NULL,
    resolved_plan_json TEXT NOT NULL,
    query_params_json TEXT NOT NULL,
    canonical_digest TEXT NOT NULL,
    storage_format TEXT NOT NULL DEFAULT 'json', -- 'json' or 'parquet'
    payload_json TEXT,
    parquet_key TEXT,
    row_count INTEGER NOT NULL,
    exactness_class TEXT NOT NULL DEFAULT 'exact',
    reproducibility_status TEXT NOT NULL DEFAULT 'reproducible',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenant(id),
    FOREIGN KEY (investigation_id) REFERENCES investigation(id)
);
CREATE INDEX IF NOT EXISTS idx_evidence_tenant ON evidence_artifact(tenant_id, investigation_id);

CREATE TABLE IF NOT EXISTS investigation_claim (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    investigation_id TEXT NOT NULL,
    evidence_id TEXT,
    hypothesis TEXT NOT NULL,
    evidence_type TEXT NOT NULL DEFAULT 'observed',
    support_status TEXT NOT NULL DEFAULT 'supporting',
    quality_flags_json TEXT NOT NULL DEFAULT '[]',
    structured_fact_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenant(id),
    FOREIGN KEY (investigation_id) REFERENCES investigation(id),
    FOREIGN KEY (evidence_id) REFERENCES evidence_artifact(id)
);
CREATE INDEX IF NOT EXISTS idx_claim_tenant ON investigation_claim(tenant_id, investigation_id);

CREATE TABLE IF NOT EXISTS decision_evidence_binding (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'primary_support',
    created_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenant(id),
    FOREIGN KEY (decision_id) REFERENCES decision(id),
    FOREIGN KEY (evidence_id) REFERENCES evidence_artifact(id)
);
CREATE INDEX IF NOT EXISTS idx_binding_tenant ON decision_evidence_binding(tenant_id, decision_id);
```

### Storage Payload Strategy & Size Controls
- **JSON Payload**: Small/scalar query results (<= 100 rows) are stored in `evidence_artifact.payload_json`.
- **Parquet Artifact**: Large tabular results (> 100 rows up to 50,000 rows / 5MB cap) are stored in `LocalObjectStore` under `objects/{tenant_id}/evidence/{artifact_id}.parquet`.
- **Sampling**: Exceeding size caps automatically enforces sampling, adding the `sampled` tag to `quality_flags`.

---

## 10. Authoritative API Contracts (`/v1/...`)

All routes strictly use the `/v1/` prefix and standard header authentication (`X-Tenant` / `X-Tenant-ID`, `X-User`):

### Investigations
- `POST /v1/investigations` (Create investigation, returns `201 Created`)
- `GET /v1/investigations` (List tenant investigations)
- `GET /v1/investigations/{id}` (Get investigation details with claims & evidence, returns `200` or `404`)
- `POST /v1/investigations/{id}/claims` (Add structured claim, returns `201 Created`)
- `GET /v1/investigations/{id}/claims` (List claims for investigation)

### Monitoring Integration
- `POST /v1/monitoring/episodes/{episode_id}/investigate` (Idempotent launch of investigation from alert)

### Evidence Snapshots
- `POST /v1/evidence` (Capture metric/dataset evidence snapshot artifact, returns `201 Created`)
- `GET /v1/evidence/{id}` (Retrieve evidence artifact & verify canonical digest)

### Decision Register Bindings
- `POST /v1/decisions/{id}/evidence` (Bind evidence snapshot to decision brief)
- `GET /v1/decisions/{id}/evidence` (List bound evidence for decision)

---

## 11. Security & Authorization Model

1. **Header Authentication Context**:
   - `x_tenant` (`X-Tenant` or `X-Tenant-ID`) and `x_user` (`X-User`).
   - Validated via `ctx(x_tenant, x_user)`.
   - Missing/invalid -> `401 demo authentication missing`.
2. **Non-Disclosing Tenant Security (Spec §23.4)**:
   - Any attempt by User A (Tenant Alpha) to request or link a resource belonging to Tenant Beta returns `404 not found` (never 403 or disclosure of resource existence).
3. **Historical Authorization Check**:
   - Retrieving historical evidence re-checks current user tenant permissions; historical access rights do not override current tenant boundaries.

---

## 12. Frontend Implementation Scope

- **New Route `/investigations`**: Filterable list/grid of open and resolved investigations.
- **New Route `/investigations/[id]`**: Deep workspace displaying question, claim list builder, metric query & snapshot tool, decision brief generator.
- **Updated Route `/decisions`**: Dedicated Decision Register workspace with lifecycle transition buttons, evidence cards, and outcome review modal.
- **Bilingual & RTL**: Dual English (`en.json`) and Arabic (`ar.json`) translations for all new UI text.
- **Verification**: `vue-tsc --noEmit` typecheck and `npm run build` production build (no Playwright dependency).

---

## 13. Comprehensive Acceptance Criteria

- **AC-01**: Monitoring episode can idempotently launch or reuse one linked investigation (`POST /v1/monitoring/episodes/{id}/investigate`).
- **AC-02**: Cross-tenant access to investigations or evidence returns a non-disclosing `404 Not Found`.
- **AC-03**: Claim records enforce valid `evidence_type` and `support_status` enums.
- **AC-04**: Numerical claims reference structured fact objects (`metric`, `value`, `unit`, `period`), not unparsed strings.
- **AC-05**: Evidence snapshot pins source dataset ID, dataset revision, metric ID, and definition version.
- **AC-06**: Retrieval of evidence snapshot recalculates and verifies the `canonical_digest` (SHA-256).
- **AC-07**: Updating an underlying source dataset or publishing a new dataset revision does NOT mutate historical evidence snapshots.
- **AC-08**: Evidence snapshot payload exceeding 50,000 rows is sampled and carries the `sampled` quality flag.
- **AC-09**: Users without current tenant access cannot retrieve historical evidence snapshots.
- **AC-10**: Transitioning a decision to `accepted` freezes its linked evidence bindings.
- **AC-11**: Editing an accepted decision creates an append-only `DecisionAmendment` rather than overwriting.
- **AC-12**: Decision status transitions strictly enforce the 12-state lifecycle in `register.py`.
- **AC-13**: Complete end-to-end operational loop works: Monitoring Episode Alert → Launch Investigation → Snapshot Evidence → Bind to Decision Brief → Approve in Decision Register.
- **AC-14**: All new UI surfaces render cleanly in Arabic with RTL layout enabled.
- **AC-15**: Existing 207 backend test suite passes with 0 regressions.
- **AC-16**: Tenant security matrix tests cover every new investigation and evidence endpoint.

---

## 14. Ordered Work Packages

### WP-00: Repository Baseline Freeze & Database Schema Migration
- **Files**: `services/analytics/decisionos_analytics/store.py`
- **Task**: Add `investigation`, `evidence_artifact`, `investigation_claim`, and `decision_evidence_binding` tables to SQLite schema initializer.
- **Completion Evidence**: Clean `git status` on frozen commit; `pytest` passes schema initialization.

### WP-01: Evidence Snapshot Engine (`backend`)
- **Files**: `services/analytics/decisionos_analytics/evidence.py`, `objectstore.py`, `api.py`
- **Task**: Implement evidence snapshot capture, SHA-256 canonical digest computation, Polars/JSON serializer, size cap/sampling flags, and `@app.post("/v1/evidence")`.
- **Completion Evidence**: `pytest tests/test_evidence.py` PASS (snapshot capture, digest verification, immutability check).

### WP-02: Investigation Workspace Core (`backend & API`)
- **Files**: `services/analytics/decisionos_analytics/investigations.py`, `api.py`
- **Task**: Implement investigation lifecycle, structured claims, episode linkage (`POST /v1/monitoring/episodes/{id}/investigate`), and API endpoints.
- **Completion Evidence**: `pytest tests/test_investigations.py` PASS (CRUD, idempotent episode launch, claim linking).

### WP-03: Decision Brief Evidence Binding (`backend & API`)
- **Files**: `services/analytics/decisionos_analytics/register.py`, `api.py`
- **Task**: Connect evidence snapshots to Decision Briefs, implement `POST /v1/decisions/{id}/evidence`, freeze context on acceptance.
- **Completion Evidence**: `pytest tests/test_decision_evidence.py` PASS (evidence binding, status transition, amendment creation).

### WP-04: Investigation & Decision Register UI (`frontend`)
- **Files**: `apps/web/pages/investigations/index.vue`, `apps/web/pages/investigations/[id].vue`, `apps/web/pages/decisions/index.vue`, `apps/web/locales/en.json`, `ar.json`
- **Task**: Build Investigation list, Investigation workspace page, Decision Register view, evidence cards, and bilingual AR/EN strings.
- **Completion Evidence**: `vue-tsc --noEmit` PASS and clean `npm run build`.

### WP-05: E2E Integration & Tenant Security Regression Suite (`testing`)
- **Files**: `services/analytics/tests/test_e2e_decision_loop.py`, `services/analytics/tests/test_tenant_security_investigations.py`
- **Task**: Add end-to-end HTTP integration test and tenant security matrix tests for all new endpoints.
- **Completion Evidence**: 100% PASS across full pytest suite (207 original + new tests) with zero regressions.

---

## 15. Implementation Readiness Verdict

```text
READY TO IMPLEMENT
```

*Explanation*: The Round 2 release remediation and security regression tests are fully committed (`4c6576d`), all verification gates pass (207 backend tests, 93% coverage, 0 frontend type/build errors), and the architecture plan is completely frozen (`docs: freeze evidence investigation decision-loop plan`).
