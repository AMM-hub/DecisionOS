You are building M3 — Workflow Analytics for DecisionOS at C:\Users\AMD\Desktop\DecisionOS.

## SPEC REFERENCE (spec §15 — Workflow and Process Intelligence)

### Key requirements
1. Analyze event histories: cases, stages, transitions, timestamps
2. Identify bottlenecks: stages where cases wait longest
3. Variant analysis: group similar process paths
4. Conformance checking: actual flows vs expected process rules
5. Case metrics: age, duration by stage, SLA status
6. Preserve unknown event types without silently dropping them

### Event data model
Each case has event history: Case ID | Event | Timestamp | Actor/team | Attributes
Event sourcing pattern with PostgreSQL event store.

## CURRENT STATE
- **Python API** on :8100 with FastAPI, polars, pydantic, uvicorn, SQLite store
- **Nuxt frontend** on :3000 with Vue 3, composables/api.ts, full types
- **37 tests passing** (core + forecasting)
- **Synthetic fixtures** at fixtures/support-tickets/ with 2 tenants, ticket events

## YOUR TASK

### 1. Install PM4Py in the analytics venv
```bash
cd services/analytics && .venv\Scripts\python -m pip install pm4py
```

### 2. Create services/analytics/decisionos_analytics/workflow.py
A module with these functions:

```
load_event_log(data) → PM4Py event log object
  - Takes polars DataFrame with case_id, event, timestamp, attributes
  - Returns PM4Py-compatible event log

bottleneck_analysis(log) → list of bottlenecks
  - For each activity: count, median duration, avg duration, waiting time
  - Returns sorted by longest median duration

variant_analysis(log) → list of process variants
  - Each variant: activities list, case count, frequency
  - Simplified variant paths (top 5 by count)

conformance_checking(log, expected_rules) → conformance results
  - expected_rules: list of {from_activity, to_activity} allowed transitions
  - Returns: fitness, precision, violated_cases count, example violations

case_metrics(data) → case-level metrics
  - By case: total_duration, stage_count, current_stage, is_overdue, sla_status
  - SLA rules configurable

throughput_times(log, unit='hours') → stage throughput analysis
  - For each stage: min, median, max, p90 throughput time
  - Entry/exit transitions with counts
```

### 3. Add workflow API endpoints to api.py
```
POST /v1/workflow/bottlenecks
  Input: { dataset_id, case_id_col, event_col, timestamp_col, attributes }
  Output: { bottlenecks: [{activity, count, median, avg, waiting_time}] }

POST /v1/workflow/variants
  Input: { dataset_id, case_id_col, event_col, timestamp_col }
  Output: { variants: [{path, case_count, frequency}], total_cases }

POST /v1/workflow/conformance
  Input: { dataset_id, case_id_col, event_col, timestamp_col, expected_rules }
  Output: { fitness, precision, violated_cases, example_violations }

POST /v1/workflow/case-metrics
  Input: { dataset_id, case_id_col, event_col, timestamp_col, sla_hours? }
  Output: { metrics: [{case_id, duration, stage_count, current, overdue, sla_status}] }

POST /v1/workflow/throughput
  Input: { dataset_id, case_id_col, event_col, timestamp_col }
  Output: { stages: [{stage, count, median, p90, from_activities, to_activities}] }
```

### 4. Create workflow frontend page
Create apps/web/pages/workflow.vue with:
- Dataset selector (reuse existing datasets from API)
- Analysis tabs: Bottlenecks | Variants | Throughput | Case Metrics
- Bottleneck view: sorted table with color-coded waiting times
- Variant view: list of process paths with frequency badges
- Throughput view: stage stats with min/median/p90 columns
- Case metrics: searchable table with SLA status badges

Use the existing Card/Badge/Muted CSS styles from app.vue.

### 5. Add types to shared/types.ts
Types for: BottleneckResult, VariantResult, ConformanceResult, CaseMetricResult, ThroughputResult, WorkflowAnalysisRequest

### 6. Add tests
Create tests/test_workflow.py with at least 6 tests covering:
- Bottleneck detection on known fixture data
- Variant analysis grouping
- Conformance checking (valid + invalid transitions)
- Case metrics with SLA
- Throughput time calculations
- Endpoint integration via TestClient

## CONSTRAINTS
- Stay ONLY under C:\Users\AMD\Desktop\DecisionOS
- Don't break existing tests (37 passing currently)
- New endpoints use /v1 prefix with X-Tenant/X-User headers
- Events table is at fixtures/support-tickets/data/tenant_alpha/ticket_events.csv
- Use PYTHONPATH="" when running tests to avoid Hermes venv leakage