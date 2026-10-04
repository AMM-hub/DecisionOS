# DecisionOS — Post-D3A Product & Pilot Decision Gate
## Operational Readiness & Next Phase Strategy

---

## 1. Accepted Baseline
- **Repository Path**: `C:\Users\AMD\Desktop\DecisionOS`
- **Branch**: `main`
- **Accepted Tag**: `decisionos-d3a-technical-accepted`
- **Commit Hash**: `834ac3c6c50cf289fbb4ce44cc8739c3e2a86505`
- **Current Quality State**:
  - 273 backend tests passing (0 failed across 3 consecutive runs + default run).
  - 90.39% total production code coverage (3,115 / 3,446 statements).
  - Frontend typecheck and production build cleanly passing (`npm run typecheck` & `npm run build`).
  - Database integrity check `ok` with zero foreign key violations.
  - Multi-tenant security matrix verified.
  - Working tree clean.

---

## 2. Technical vs Product vs Real-World Status

| Dimension | Current Status | Description |
|---|---|---|
| **Technical Capability** | **COMPLETE (D2 + D3-A)** | End-to-end code, APIs, schemas, temporal safety, calibration, evidence digests, investigations, and decision lifecycle exist and pass full automated certification. |
| **Product Readiness** | **PARTIAL** | Core user surfaces (`/uploads`, `/datasets`, `/metrics`, `/monitoring`, `/risk`, `/investigations`, `/decisions`) exist, but setup requires developer scripting or multi-step manual API calls. |
| **Real-World Model Validation** | **NOT APPROVED** | Models carry `synthetic_validated` / `evaluation_only` status. Real production deployment requires domain owner sign-off, historical tenant datasets, and out-of-sample decision utility validation. |

---

## 3. D0–D5 Reassessment

Using the DecisionOS Master Specification governance framework:

| Stage | Implementation Status | Real-World Gate Status | Verdict & Gap |
|---|---|---|---|
| **D0 — Bounded Problem** | **COMPLETE** | **PARTIAL** | Problem schemas, target specs, and datasets are implemented; requires named pilot customer/owner. |
| **D1 — Analytical Core** | **COMPLETE** | **PASSED** | Certified metric engine, grain proof, execution engine, and error classification are operational. |
| **D2 — Decision Loop** | **COMPLETE** | **PARTIAL** | Full loop (Alert $\rightarrow$ Investigation $\rightarrow$ Claim $\rightarrow$ Evidence $\rightarrow$ Decision Brief $\rightarrow$ Outcome) is coded; needs repeated real customer decision cycles. |
| **D3-A — Hardened Risk & Forecast** | **COMPLETE (Technical)** | **EVALUATION ONLY** | Rolling-origin forecasting, Platt calibration, capacity thresholds, and non-causal risk UI pass technical gates; real-world model approval pending. |
| **D3-B — Survival & Backlog** | **UNSTARTED** | **UNSTARTED** | Deferred to future scope; not required for initial operational pilot. |
| **D4 — Action Execution** | **UNSTARTED** | **UNSTARTED** | Human-in-the-loop decisions preserved; automated execution deferred. |
| **D5 — Autonomous Loop** | **UNSTARTED** | **UNSTARTED** | System governance strictly forbids autonomous decision execution at this stage. |

---

## 4. Current Product Journey

Tracing a real user journey through the current repository:

```
[CSV Upload] (/uploads) -> [Grain Proof] (/datasets) -> [Metric Def] (/metrics)
                                                                |
                                                                v
[Decision Review] (/decisions) <- [Investigation] <- [Alert / Risk Queue] (/monitoring & /risk)
```

- **Data Ingest (`/uploads`)**: `READY` — CSV upload, quarantine scan, parse preview.
- **Grain & Dataset (`/datasets`)**: `READY` — Grain proof candidates, key confirmation, revision publishing.
- **Metric Definitions (`/metrics`)**: `READY` — Certified count/ratio metrics, versioning, publication.
- **Monitoring & Alerts (`/monitoring`)**: `READY` — Rule setup, episode detection, health status.
- **Predictive Risk (`/risk`)**: `READY (Technical)` — Risk queue, probability calibration status, non-causal factors, unsupported state handling.
- **Investigation (`/investigations`)**: `READY` — Multi-source investigation (`monitoring_episode`, `predictive_risk`), structured claims, immutable evidence attachment.
- **Decision Brief & Register (`/decisions`)**: `READY` — Decision brief creation, evidence binding, lifecycle transitions (`draft` $\rightarrow$ `proposed` $\rightarrow$ `accepted` $\rightarrow$ `active` $\rightarrow$ `review_due` $\rightarrow$ `evaluated`).
- **Outcome Review**: `PARTIAL` — Backend `OutcomeRecord` and verdict APIs are functional; frontend lacks comparative "Before vs After" metric visualization.
- **Onboarding & Configuration**: `TECHNICALLY PRESENT BUT NOT PRODUCTIZED` — Requires manual API calls or database scripts to configure initial pilot setup.

---

## 5. Largest Product Bottleneck

**The Biggest Product Gap**: **Pilot Setup, Configuration & Executive Outcome Visualization**.

If an Operations Manager attempted to run DecisionOS tomorrow, they would get stuck on:
1. **Initial Setup Complexity**: Creating the initial dataset, grain confirmation, metric definition, alert rule, and risk target requires executing sequential manual HTTP API requests or running Python scripts.
2. **Data Refresh Automation**: Data ingestion currently requires manual file uploads; there is no scheduled background sync or live file watcher.
3. **Outcome Review Visualization**: Operations managers cannot easily see a unified executive dashboard comparing metric performance *before* vs *after* a decision was implemented.

---

## 6. Pilot Candidate Analysis

Evaluating 3 operational domains compatible with DecisionOS:

1. **Candidate 1: Support Ticket SLA Management (Customer Operations)**
   - *Business Problem*: High SLA breach rate on complex Tier-2 technical support tickets.
   - *Decision Owner*: Customer Support Operations Director.
   - *Case Entity*: Support Ticket (`ticket_id`).
   - *Main KPI*: 24h Resolution SLA Breach Rate (Target $< 5\%$).
   - *Prediction Opportunity*: Case-level 24h breach risk scoring at $t_{obs} = 4\text{h}$ after ticket creation.
   - *Decision to Improve*: Reallocate Tier-2 support engineers to high-risk ticket queues.
   - *Fit*: **EXCELLENT**. Aligns 100% with current dataset schemas, workflow engines, and risk queues.

2. **Candidate 2: Customer Onboarding & KYC Approval Queue (Fintech Operations)**
   - *Business Problem*: Backlog accumulation in manual document verification queues.
   - *Decision Owner*: Operations Risk & Compliance Manager.
   - *Case Entity*: Verification Application (`app_id`).
   - *Main KPI*: Application Processing Time (Target $< 48\text{h}$).
   - *Prediction Opportunity*: Breach risk scoring when application reaches manual review stage.
   - *Decision to Improve*: Reassign compliance staff or fast-track low-risk verified applications.
   - *Fit*: **GOOD**. Fits workflow case structure, but requires additional document type metadata.

3. **Candidate 3: Healthcare Discharge & Bed Allocation (Hospital Operations)**
   - *Business Problem*: Emergency department bed shortages due to delayed ward discharge approvals.
   - *Decision Owner*: Hospital Operations Director.
   - *Case Entity*: Patient Admission (`patient_id`).
   - *Main KPI*: Discharge Delay Hours (Target $< 2\text{h}$).
   - *Fit*: **MODERATE**. Fits metric definitions, but requires complex shift schedules and HIPAA data masking.

---

## 7. Selected Golden Pilot

**RECOMMENDED GOLDEN PILOT**: **Support Ticket SLA & Queue Operations (Customer Operations)**

### Why It Is the Best First Pilot
- **Architectural Match**: Exercises 100% of the DecisionOS stack (Ingestion $\rightarrow$ Grain $\rightarrow$ Metrics $\rightarrow$ Monitoring $\rightarrow$ Risk $\rightarrow$ Investigation $\rightarrow$ Evidence $\rightarrow$ Decision Brief $\rightarrow$ Outcome Review).
- **Data Availability**: Requires standard tabular event log format (`case_id`, `timestamp`, `activity`, `resource`, `priority`, `category`).
- **Clear Operational ROI**: Directly measures SLA breach reduction, time-to-decision, and decision outcome effectiveness.

---

## 8. Golden Business Questions

A targeted 12-question operational suite for the Golden Pilot:

| # | Question | System Surface | Output | Evidence Type | Supported Today? |
|---|---|---|---|---|---|
| 1 | What is the current 24h SLA breach rate across queues? | `/metrics` | Time-series chart & current value | Observed | **YES** |
| 2 | Where is delay concentrated in the workflow? | `/workflow` | Bottleneck activity map | Observed | **YES** |
| 3 | Which active open cases exceed 18h age? | `/workflow` | Filtered case table | Observed | **YES** |
| 4 | Which open cases have a $> 70\%$ probability of breaching SLA in 24h? | `/risk` | Calibrated risk queue | Estimated | **YES** |
| 5 | Why was an SLA spike alert triggered for Queue B? | `/monitoring` | Alert episode detail | Observed | **YES** |
| 6 | What features influenced the high breach risk score on Ticket #8021? | `/risk` | Non-causal factor list | Estimated | **YES** |
| 7 | What metric evidence supports the claim that Tier-2 staffing is the bottleneck? | `/investigations` | Evidence artifact with digest | Observed | **YES** |
| 8 | What decision brief is proposed to resolve Queue B SLA breaches? | `/decisions` | Structured decision brief | Decision Brief | **YES** |
| 9 | What evidence is bound to support this staffing reallocation decision? | `/decisions` | Immutable evidence links | Observed/Estimated | **YES** |
| 10 | Has the decision been formally accepted and scheduled for review? | `/decisions` | Lifecycle status (`accepted`) | Register Audit | **YES** |
| 11 | Did the SLA breach rate decrease 14 days after implementing the reallocation decision? | `/decisions` | Comparative Outcome Verdict | Observed | **PARTIAL** |
| 12 | Did the reallocation decision cause unintended counter-metric degradation in Queue A? | `/decisions` | Counter-metric comparison | Observed | **PARTIAL** |

---

## 9. Pilot Data Contract

### Schema Specification (`support_tickets_event_log.csv`)
- `ticket_id` (STRING, Required): Unique case identifier.
- `timestamp` (DATETIME UTC, Required): Event timestamp.
- `activity` (STRING, Required): Workflow stage (`created`, `assigned`, `investigating`, `resolved`).
- `resource` (STRING, Optional): Agent or team ID.
- `priority` (STRING, Optional): Ticket priority (`high`, `medium`, `low`).
- `category` (STRING, Optional): Issue category (`billing`, `technical`, `access`).
- `sla_deadline` (DATETIME UTC, Required): Hard SLA deadline.
- `available_at` (DATETIME UTC, Required): Timestamp when event became available.

### Data Policy Expectations
- **Historical Depth**: Minimum 90 days of historical event data.
- **Outcome Maturity**: 7-day outcome window maturity enforced for evaluation.
- **Freshness**: Daily or hourly batch ingestion.
- **Time Basis**: Strict `calendar_utc`.

---

## 10. Semantic Readiness
- Certified metric definitions (`m_sla_breach_rate`, `m_avg_resolution_hours`) use versioned JSON specifications.
- Metric publication and grain confirmation prevent querying unverified data schemas.
- **Prerequisite Gap**: Add an intuitive UI modal for configuring SLA breach threshold metrics directly without raw JSON payload editing.

---

## 11. Configuration / Onboarding Readiness
- **Current State**: Onboarding requires 6 sequential REST API calls (`/v1/uploads`, `/v1/datasets/{id}/grain-confirmation`, `/v1/metrics/definitions`, `/v1/monitoring/rules`, `/v1/predictive/targets`, `/v1/predictive/models`).
- **Required Productization**: Build a unified **Pilot Setup Wizard** (`/pilot/setup`) that guides an admin through uploading data, confirming grain, creating SLA metrics, establishing alert rules, and initializing predictive risk targets in one guided flow.

---

## 12. Outcome Review Readiness
- **Backend**: `OutcomeRecord` structure, `Verdict` enums (`supported_improvement`, `no_clear_change`, `deterioration`), and `record_outcome()` API are complete and tested.
- **Frontend Gap**: Add an **Outcome Review Comparison Widget** on `/decisions` displaying side-by-side metric charts for the 14 days *prior* to decision implementation vs the 14 days *after* implementation.

---

## 13. Predictive Real-World Approval Path

To transition a predictive model from `TECHNICALLY ACCEPTED` (`evaluation_only`) to `REAL-WORLD APPROVED`:

```
[Synthetic Validation] -> [Pilot Historical Data] -> [Temporal Holdout Test] -> [Calibration Check] -> [Owner Sign-off] -> [REAL-WORLD APPROVED]
```

1. **Historical Dataset**: Ingest $\ge 90$ days of real customer event history.
2. **Temporal Holdout Evaluation**: Evaluate model out-of-sample on the last 30 matured days.
3. **Baseline Superiority**: Verify candidate model outperforms `BaseRateClassifier` by Brier score improvement $> 0.01$.
4. **Calibration Verification**: Confirm `PlattCalibrator` achieves `probability_status = "calibrated"`.
5. **Operational Capacity Threshold**: Validate threshold alignment with real support team review capacity.
6. **Domain Owner Sign-off**: Product/Operations Owner explicitly approves model transition to `active`.

---

## 14. Pilot-Safe Mode
- All predictive risk screens (`/risk`) and API outputs clearly display governance badges:
  - **`TECHNICALLY VALIDATED (EVALUATION ONLY)`** for synthetic/demo models.
  - **`REAL-WORLD APPROVED`** only after explicit domain owner sign-off.
- Prevents users from mistaking synthetic test predictions for production-validated operational risk.

---

## 15. Deployment / Operations Readiness
- Single-node SQLite control plane store (`control.sqlite3`) and local object store handle up to 500,000 events effortlessly for a bounded 4-week pilot.
- Environment configuration via standard environment variables (`DATA_DIR`, `PORT`).
- Database backup via simple SQLite file copy or `VACUUM INTO`.

---

## 16. Reporting / Executive Readiness
- Build a single **Executive Pilot Command Center** (`/pilot/dashboard` or `/`) bringing together:
  1. Active SLA breach alerts.
  2. High-risk cases requiring immediate attention.
  3. Open proactive investigations.
  4. Pending decision briefs awaiting approval.
  5. Completed decision outcome review verdicts.

---

## 17. Candidate Next-Phase Comparison

| Option | Focus Area | Pilot Value | Technical Risk | Recommendation |
|---|---|---|---|---|
| **A. PILOT-01 (Controlled Pilot Readiness)** | Onboarding wizard, pilot dashboard, outcome review UI | **HIGH** | **LOW** | **RECOMMENDED** |
| **B. D3-B (Survival & Backlog)** | Cox models, queueing theory, backlog projections | **LOW** | **HIGH** | **DEFER** |
| **C. Productization & Enterprise Admin** | SSO, SCIM, RBAC, Kubernetes manifests | **MEDIUM** | **MEDIUM** | **DEFER** |
| **D. Advanced Conversational AI** | LLM natural language queries, chat interfaces | **LOW** | **HIGH** | **DEFER** |

---

## 18. Should D3-B Come Next?

**NO / NOT YET**

### Why D3-B Should NOT Be Built Next
- DecisionOS has achieved complete technical capability for D2 (Operational Decision Loop) and D3-A (Forecast Hardening & Classification Risk).
- The primary barrier to commercial adoption is **not a lack of complex survival/queuing algorithms**, but rather **onboarding friction and the lack of a unified pilot user experience**.
- Building D3-B now would add complex mathematical overhead before validating that operations managers can successfully use DecisionOS to make, track, and review real decisions.

---

## 19. Recommended Next Phase

**PILOT-01 — Controlled Operational Pilot Readiness**

---

## 20. Must / Should / Out of Scope

### MUST HAVE (PILOT-01)
- Unified Pilot Setup Wizard (`/pilot/setup`) for zero-code dataset onboarding, grain proof, metric definition, and alert configuration.
- Executive Pilot Command Center (`/pilot/dashboard`) summarizing alerts, high-risk cases, active investigations, decision briefs, and outcome verdicts.
- Outcome Review Comparative UI (`/decisions`) showing side-by-side metric performance before vs after decision acceptance.
- Real-World Model Approval governance UI flow.
- Automated daily batch dataset ingestion script / file watcher.

### SHOULD HAVE
- CSV/PDF export for Decision Briefs and Evidence Artifacts.
- Enhanced bilingual AR/EN search on pilot dashboard.

### OUT OF SCOPE
- Survival analysis and Cox proportional hazards (D3-B).
- Backlog projections and queuing network models (D3-B).
- Autonomous decision execution (D4/D5).
- LLM/AI conversational chat features.

---

## 21. Target User Journey

```
[1. Admin Setup Wizard] -> [2. Daily Batch Ingest] -> [3. Executive Dashboard]
                                                              |
                                                              v
[7. Outcome Review] <- [6. Decision Brief] <- [5. Investigation] <- [4. Risk Queue / Alert]
```

1. **Admin Setup**: Operations Admin runs `/pilot/setup` wizard to upload ticket event log, confirm grain, and set 24h SLA target.
2. **Daily Batch Ingest**: System ingests daily ticket updates automatically.
3. **Executive Dashboard**: Operations Director opens `/pilot/dashboard` to view current SLA breach rate (3.2%) and active alerts.
4. **Risk Queue**: Support Lead checks `/risk` to review 4 tickets flagged with $> 75\%$ 24h breach risk.
5. **Investigation**: Support Lead clicks "Launch Investigation" on Ticket #8021; system attaches metric evidence showing Tier-2 queue bottleneck.
6. **Decision Brief**: Operations Director creates decision brief to temporarily reallocate 2 agents to Tier-2 Queue B; decision is formally accepted.
7. **Outcome Review**: 14 days later, system prompts for outcome review; side-by-side chart confirms SLA breach rate dropped to 1.1% (`supported_improvement`).

---

## 22. Success Metrics

### System Success Metrics
- 100% of setup steps completed via UI wizard without manual code/API execution.
- 0 data integrity errors during daily batch ingestion.
- 100% decision traceability from risk alert to outcome verdict.

### Pilot Business Success Metrics
- Reduction in operational SLA breach rate (e.g. from $> 5\%$ to $< 2\%$).
- Reduction in average time-to-decision for operational queue reallocations.
- Positive outcome verdict on $\ge 80\%$ of implemented decisions.

---

## 23. Exit Gate

To close **PILOT-01**:
1. At least 1 complete Golden Pilot dataset onboarded via UI wizard.
2. Named Pilot Operations Owner assigned.
3. Executive Pilot Command Center operational.
4. End-to-end user journey executed from data upload to completed decision outcome review.
5. Real-World Model Approval workflow functional.
6. All automated backend tests (273+ baseline) pass with $\ge 90\%$ code coverage.
7. Frontend typecheck and build pass cleanly.

---

## 24. NOT NOW

The following capabilities are explicitly deferred:
- **D3-B Survival & Cox Models**: Deferred until PILOT-01 validation complete.
- **Backlog & Queuing Theory Projections**: Deferred to D3-B.
- **Autonomous Decision Execution**: Strictly out of scope (human governance required).
- **LLM / Conversational Vector Search**: Deferred.
- **Enterprise SSO / SCIM / Kubernetes Helm Charts**: Deferred.

---

## 25. Ordered Work Packages

### WP-00 — Pilot Contract, Ingestion & Data Pipeline Hardening
- **Goal**: Implement pilot data contract validation and background file-watcher ingestion.
- **Backend**: Add file-watcher daemon / batch ingestion API in `api.py` & `pipeline.py`.
- **Frontend**: Add data ingestion status indicator in `/uploads`.
- **Tests**: Add unit tests for batch ingestion and pilot data schema validation.

### WP-01 — Guided Pilot Setup Wizard (`/pilot/setup`)
- **Goal**: Build single multi-step setup wizard combining data upload, grain confirmation, metric definition, alert rule, and risk target creation.
- **Frontend**: Create `apps/web/pages/pilot/setup.vue`.
- **Backend**: Add `/v1/pilot/bootstrap` endpoint in `api.py`.
- **Tests**: Add E2E tests for pilot bootstrap API.

### WP-02 — Executive Pilot Command Center (`/pilot/dashboard`)
- **Goal**: Build unified operational command center for executive pilot owners.
- **Frontend**: Create `apps/web/pages/pilot/dashboard.vue` summarizing alerts, risk queue, active investigations, pending decisions, and outcome verdicts.
- **Backend**: Add `/v1/pilot/summary` aggregation endpoint in `api.py`.
- **Tests**: Add unit tests for summary aggregation logic.

### WP-03 — Decision Outcome Review UI & Comparative Metrics
- **Goal**: Build side-by-side metric performance comparison UI for decision outcome reviews.
- **Frontend**: Update `apps/web/pages/decisions.vue` with comparative "Before vs After" metric chart component.
- **Backend**: Add `/v1/decisions/{id}/outcome-comparison` endpoint.
- **Tests**: Add unit tests for pre/post decision window metric comparison.

### WP-04 — Real-World Model Approval Governance Workflow
- **Goal**: Implement formal UI and backend workflow for promoting evaluation models to `REAL-WORLD APPROVED`.
- **Frontend**: Add model promotion governance modal in `apps/web/pages/risk.vue`.
- **Backend**: Add `/v1/predictive/models/{id}/approve-real-world` endpoint enforcing temporal holdout validation.
- **Tests**: Add unit tests for model real-world approval gate checks.

### WP-05 — E2E Golden Pilot Validation & Certification
- **Goal**: Certify complete Golden Pilot user journey using Support Ticket SLA dataset fixture.
- **Tests**: Add comprehensive E2E integration test suite `test_pilot_e2e_journey.py`.
- **Certification**: Verify 100% test pass rate, $\ge 90\%$ code coverage, frontend typecheck/build pass.

---

## 26. Acceptance Criteria

- **AC-01**: Admin can complete pilot onboarding via `/pilot/setup` without manual REST calls or database edits.
- **AC-02**: Executive Pilot Dashboard (`/pilot/dashboard`) aggregates active alerts, high-risk cases, open investigations, and pending decisions.
- **AC-03**: Decision page (`/decisions`) renders comparative metric visualization comparing 14-day pre-decision vs post-decision performance.
- **AC-04**: Models require explicit temporal holdout validation and owner approval before displaying `REAL-WORLD APPROVED` badge.
- **AC-05**: Full Golden Pilot user journey passes automated E2E integration tests.
- **AC-06**: All existing 273 backend unit tests pass with zero regressions.
- **AC-07**: Total production code coverage remains $\ge 90.00\%$.
- **AC-08**: Frontend typecheck and production build pass cleanly.

---

## 27. Risks / Open Questions

- **Risk 1**: Customer event log timestamps may have timezone inconsistencies.
  - *Mitigation*: Strictly enforce ISO 8601 UTC parsing in `pipeline.py`.
- **Risk 2**: Operations managers may forget to record decision outcome reviews when due.
  - *Mitigation*: Display "Review Overdue" badges on the Executive Pilot Dashboard.

---

## 28. Implementation Readiness

This document is a **PRODUCT ARCHITECTURE & PLANNING SPECIFICATION ONLY**. No production code or test files have been modified.

---

PILOT READINESS:
PARTIAL

D3-B NEXT:
NOT YET

NEXT PHASE:
PILOT-01 — Controlled Operational Pilot Readiness

WHY:
DecisionOS has complete technical operational capabilities (D2 decision loop + D3-A forecasting & risk classification) with 273 tests and 90.39% coverage. However, real-world operational adoption is blocked by configuration onboarding friction, manual data refresh, and lack of an executive outcome review command center. Building complex survival/backlog models (D3-B) prior to validating a real operational loop with a pilot owner would widen technical debt without delivering commercial pilot readiness.

FIRST WORK PACKAGE:
WP-00 — Pilot Contract, Ingestion & Data Pipeline Hardening

IMPLEMENTATION STATUS:
PLANNING ONLY — DO NOT CODE
