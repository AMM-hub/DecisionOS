# DecisionOS — Post-D2 Next Phase Recommendation

## 1. Accepted Baseline

- **Repository**: `C:\Users\AMD\Desktop\DecisionOS`
- **Branch**: `main`
- **Accepted Tag**: `decisionos-d2-accepted`
- **HEAD Commit**: `4aa9eafa95a73df18ac003e7de5f5786349c7075`
- **Backend Quality**: 245 tests passing (100% pass rate across 4 consecutive suite runs), 90.05% total production coverage.
- **Frontend Quality**: `npm run typecheck` PASS (0 errors), `npm run build` PASS.
- **Database & Security**: Foreign keys enabled (`PRAGMA foreign_keys = 1`), zero integrity errors, 0 orphan records, multi-tenant isolation enforced with non-disclosing 404 security contract.
- **D2 Closed Scope**: Monitoring / Workflow → Investigation → Structured Claims → Immutable Evidence → Decision Brief → Decision Register → Acceptance / Review Context.

---

## 2. Current Product Capability Map

Based on independent inspection of the `main` repository:

| Capability Area | Status | Repository Evidence |
|---|---|---|
| **Data Ingestion & Datasets** | IMPLEMENTED | [pipeline.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/pipeline.py), [parsing.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/parsing.py), [uploads.vue](file:///C:/Users/AMD/Desktop/DecisionOS/apps/web/pages/uploads.vue), [datasets.vue](file:///C:/Users/AMD/Desktop/DecisionOS/apps/web/pages/datasets.vue) |
| **Semantic Metrics & Definitions** | PARTIAL | [semantics.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/semantics.py), [metrics.vue](file:///C:/Users/AMD/Desktop/DecisionOS/apps/web/pages/metrics.vue) (Count/Ratio created, missing semantic release versioning UI) |
| **Data Exploration & Analysis** | BACKEND ONLY | [execution.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/execution.py) (`MetricQueryRequest`), missing visual explore studio |
| **Dashboards & Executive Views** | PARTIAL | [index.vue](file:///C:/Users/AMD/Desktop/DecisionOS/apps/web/pages/index.vue) (Baseline metric cards, missing governed ChartSpec dashboards) |
| **Contextual Monitoring & Alerts** | IMPLEMENTED | [monitoring.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/monitoring.py), [monitoring.vue](file:///C:/Users/AMD/Desktop/DecisionOS/apps/web/pages/monitoring.vue), `test_monitoring.py` |
| **Workflow / Process Mining** | IMPLEMENTED | [workflow.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/workflow.py), [workflow.vue](file:///C:/Users/AMD/Desktop/DecisionOS/apps/web/pages/workflow.vue), `test_workflow.py` |
| **Investigations & Claims** | IMPLEMENTED | [investigations.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/investigations.py), [index.vue](file:///C:/Users/AMD/Desktop/DecisionOS/apps/web/pages/investigations/index.vue), `[id].vue` |
| **Immutable Evidence Artifacts** | IMPLEMENTED | [evidence.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/evidence.py), [objectstore.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/objectstore.py), `test_evidence.py` |
| **Decision Briefs & Register** | IMPLEMENTED | [register.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/register.py), [decisions.vue](file:///C:/Users/AMD/Desktop/DecisionOS/apps/web/pages/decisions.vue), `test_register.py` |
| **Time-Series Forecasting** | PARTIAL | [forecasting.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/forecasting.py), [forecasts.vue](file:///C:/Users/AMD/Desktop/DecisionOS/apps/web/pages/forecasts.vue) (Baseline ARIMA/ExpSmoothing, missing fold-validation) |
| **LP Optimization Scenarios** | PARTIAL | [optimization.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/optimization.py), [scenarios.vue](file:///C:/Users/AMD/Desktop/DecisionOS/apps/web/pages/scenarios.vue) (Baseline PuLP LP solver, missing sensitivity & queue integration) |
| **Discrete Event Simulation** | BACKEND ONLY | [simulation.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/simulation.py) (SimPy engine with unit tests, missing UI integration) |
| **Predictive Risk (Classification)** | NOT IMPLEMENTED | No classification risk models, calibration curves, or risk ranking in codebase |
| **Survival & Backlog Projection** | NOT IMPLEMENTED | No Cox proportional hazards or time-to-event survival models in codebase |
| **Causal Study Evaluation** | SCAFFOLDED | `OutcomeRecord` schema in `register.py`, missing statistical DiD/ITS study engine |
| **Governed Actions / Webhooks** | NOT IMPLEMENTED | No action flows, payload-bound approvals, or webhook execution engine |
| **Search & Catalog** | SCAFFOLDED | [bilingual.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/bilingual.py) (Backend label search, missing global catalog search UI) |
| **AI / Conversational Gateway** | NOT IMPLEMENTED | No LLM gateway or conversational assistant endpoints |

---

## 3. D0–D5 Reassessment

Evaluated against Section 30.2 of the Master Specification:

| Stage | Specification Gate | Technical Implementation Status | Real Pilot / Business Validation Status | Overall Stage Status |
|---|---|---|---|---|
| **D0 — Validate & Design** | Authorized source, named buyer, achievable pilot scope | COMPLETE | MOSTLY COMPLETE (Golden question fixtures established) | **MOSTLY COMPLETE** |
| **D1 — Trusted Analytical Core** | Secure workspace, ingestion, semantic definitions, evidence, bilingual UI | MOSTLY COMPLETE (Data, parsing, PM4Py, baseline forecasting/scenarios done) | MOSTLY COMPLETE (Tested on sample datasets) | **MOSTLY COMPLETE** |
| **D2 — Operational Loop** | Workflow metrics, data alerts, investigations, decision register, outcome reviews | COMPLETE (Backend models, tables, routes, UI screens, tests 100% done) | PENDING PILOT (Requires live operational use & decision outcome reviews) | **TECHNICAL COMPLETE / PILOT PENDING** |
| **D3 — Predictive Capability** | Validated time-series, classification risk, survival, and backlog projection | PARTIAL (Baseline forecasting exists; risk scoring & survival missing) | NOT STARTED | **PARTIAL / NEXT CANDIDATE** |
| **D4 — Scenario & Evaluation** | Valid optimization/simulation, decision briefs, causal study evaluation | PARTIAL (LP solver & SimPy backend exist; causal evaluation missing) | NOT STARTED | **PARTIAL** |
| **D5 — Enterprise Expansion** | Contract-driven integrations, private deployment, advanced scale/autonomy | NOT STARTED | NOT STARTED | **NOT STARTED** |

---

## 4. Current End-to-End Product Loop

The operational loop implemented today works as follows:

```
[Ingested Dataset / PM4Py Log]
         │
         ▼
[Monitoring Alert Rule / Episode]
         │
         ▼
[Investigation Created (Ad-Hoc / Episode)]
         │
         ▼
[Structured Claims & Immutable Evidence Captured]
         │
         ▼
[Decision Brief Drafted (Problem, Options, Trade-offs)]
         │
         ▼
[Decision Registered (Draft → Proposed → Accepted)]
```

### Where the Chain Breaks Today:

1. **Reactive Trap (The Operational Bottleneck)**: Investigations currently trigger **only after** an SLA breach or alert episode has already occurred. Operators are constantly reacting to past failures rather than anticipating risk.
2. **Missing Risk Prioritization**: Operators with 50 open workflow cases cannot determine which 5 cases are at 90% risk of breaching resolution deadlines within the next 2 hours.
3. **Disconnected Decision Execution**: Accepted decisions in the register cannot trigger proactive capacity allocation or operational adjustments because DecisionOS lacks predictive lead time.

---

## 5. Biggest Remaining Product Gaps

1. **Predictive Risk & Survival Projection Gap (D3)**: DecisionOS cannot project time-to-resolution survival curves or assign calibrated risk scores to active workflow cases/episodes.
2. **Decision Outcome Evaluation & Causal Learning Gap (D4/W22)**: When a decision reaches `review_due`, there is no automated statistical evaluation (pre/post, difference-in-differences) to measure whether the decision achieved its expected effect.
3. **Governed Actions & Automation Execution Gap (W24)**: Accepted decisions cannot emit signed webhook payloads or structured action requests to external systems (ERP/EHR/ServiceNow).
4. **Visual Data Exploration & Governed Dashboards Gap (W11)**: Users cannot build custom drag-and-drop ChartSpec dashboards or explore metrics without hitting fixed page templates.

---

## 6. Candidate Phase Comparison

| Candidate Phase | Business Value | Existing Backend | Existing Frontend | Analytical Risk | Time to Value | Pilot Impact | Recommended Score (1-10) |
|---|---|---|---|---|---|---|---|
| **A. Semantic Governance** | Medium | Medium (`semantics.py`) | Medium (`metrics.vue`) | Low | 3-4 weeks | Medium | 6.5 |
| **B. Governed Dashboards** | Medium | Low | Medium | Low | 3-4 weeks | Medium | 6.0 |
| **C. Search & Explore** | Low-Medium | Low (`bilingual.py`) | Low | Low | 2-3 weeks | Low | 5.5 |
| **D. AI / Conversational** | High | Low | Low | High | 5-6 weeks | Low (High Risk) | 4.5 |
| **E/F. Predictive Risk & Survival (D3)** | **VERY HIGH** | **High (`forecasting.py`, `workflow.py`)** | **Medium (`forecasts.vue`, `workflow.vue`)** | **Medium** | **3-4 weeks** | **VERY HIGH** | **9.5 (WINNER)** |
| **H. Causal Evaluation** | High | Low (`register.py` schema) | Low | High | 4-5 weeks | High | 7.5 |
| **J. Governed Actions** | High | Low | Low | Medium | 3-4 weeks | High | 7.0 |

---

## 7. Should D3 Come Next?

### **YES — Specifically D3-A: Predictive Risk & Operational Forecasting (W18 + W19 + W17 Expansion)**

#### Why YES?
1. **Solves the #1 Product Flaw of D2**: D2 established the investigation and decision loop, but it is purely reactive. Adding **Classification Risk Scoring (W18)** and **Survival / Backlog Projection (W19)** allows DecisionOS to predict SLA breaches *before* they occur, transforming DecisionOS from a post-incident log reader into a **proactive decision system**.
2. **Direct Architectural Extension of Accepted D2 Code**:
   - `workflow.py` (PM4Py event logs) provides event timestamps and case state history needed for Kaplan-Meier / Cox survival analysis.
   - `monitoring.py` (Alert Episodes) provides the episode triggers that consume predictive risk scores.
   - `forecasting.py` provides the time-series foundation to add backtest fold-validation and prediction interval evidence.
3. **Fulfills the Spec Delivery Sequence**: Section 30.2 explicitly specifies Stage D3 (Predictive capability: W17, W18, W19) as the immediate successor to Stage D2 (Operational loop).

---

## 8. Recommended Next Phase

### **Phase Name**: `D3-A: Forecast Hardening & Case-Level Classification Risk`

#### Scope Summary:
Transform DecisionOS into a proactive operational decision platform by adding:
1. **Forecasting Fold Validation & Evidence (W17)**: Rolling-origin 3-fold cross-validation, MASE metric, prediction interval coverage, and evidence artifact persistence.
2. **Classification Risk Scoring Engine (W18)**: Calibrated risk probability (0.0 to 1.0) for active workflow cases breaching SLA thresholds, Logistic/RandomForest models, Platt scaling, and capacity-based thresholding.
3. **Proactive Investigation Launch UI**: Proactive risk-based investigation creation directly from high-risk active workflow cases.
*(Survival Cox W19 and Backlog Conservation W19 are deferred to D3-B to ensure a strictly bounded, mathematically valid scope).*

---

## 9. Why This Phase Wins

- **What it Unlocks**: Proactive investigations launched *before* operational failure happens.
- **What Existing Components it Reuses**:
  - Backend: `workflow.py`, `forecasting.py`, `monitoring.py`, `evidence.py`, `investigations.py`, `objectstore.py`, `store.py`.
  - Frontend: `workflow.vue`, `monitoring.vue`, `forecasts.vue`, `investigations/[id].vue`.
- **What Future Phases Depend On It**: Stage D4 (Scenario Optimization & Simulation) requires predictive risk bounds and survival probability inputs to constrain optimization solvers (W20/W21).
- **What Happens if Postponed**: DecisionOS remains a reactive post-incident reporting tool, severely limiting its value proposition to enterprise operations managers.

---

## 10. Must / Should / Out of Scope

### MUST HAVE (In-Scope for D3-A):
- **W18 Classification Risk Model**: Logistic/RandomForest risk classifier with probability calibration curve (Platt scaling/Isotonic), feature importance ranking, and threshold assignment.
- **W19 Survival & Backlog Model**: Kaplan-Meier survival probability estimator and Cox proportional hazards hazard ratios for active event log cases (`workflow.py`).
- **W17 Forecast Evaluation Gate**: Held-out temporal cross-validation (backtesting), MASE calculation, and 80%/95% prediction intervals.
- **Evidence Binding**: Risk evaluation summaries and survival curves serialized as immutable Evidence Artifacts (`storage_format = "json"` / `"parquet"`).
- **UI Integration**: Risk score badges, survival curve visualizer, and "Launch Proactive Investigation" button on `workflow.vue` and `monitoring.vue`.

### SHOULD HAVE:
- Risk drift warning when feature distribution strays from training window.
- Custom risk threshold slider (e.g. alert when breach probability > 75%).

### OUT OF SCOPE (Deferred to D3-B / D4):
- Deep Learning / Neural Network forecasting models (e.g. N-BEATS, Temporal Fusion Transformers).
- Automated ML model retrain pipelines with external model registries (MLflow).
- Governed Action Execution / Webhook dispatch (W24).
- Causal Effect Evaluation (W22).

---

## 11. Target User Journey

```
Operations Manager opens /workflow or /monitoring page
                     │
                     ▼
System displays active cases with "Predictive Breach Risk" score (e.g. Case #842: 88% Risk of SLA breach in 3.5 hrs)
                     │
                     ▼
Manager clicks "Inspect Risk Details"
                     │
                     ▼
System renders Kaplan-Meier Survival Curve & Top Risk Drivers (e.g. +34% delay from vendor approval step)
                     │
                     ▼
Manager clicks "Launch Proactive Investigation"
                     │
                     ▼
System pre-populates Investigation with Risk Evidence & Kaplan-Meier Artifact bound
                     │
                     ▼
Manager drafts & accepts Decision Brief ("Re-route Case #842 to Express Team B")
                     │
                     ▼
Decision registered in Decision Register with baseline expectation attached
```

---

## 12. Backend Impact

### New Python Submodule:
- `decisionos_analytics/risk.py`: Implements `RiskClassifier`, `SurvivalEngine`, calibration metrics, feature vector extraction from PM4Py event logs (`workflow.py`).

### Modified Python Modules:
- `decisionos_analytics/forecasting.py`: Add `backtest_evaluate()` with held-out fold validation (MASE) and prediction intervals (`pi_80`, `pi_95`).
- `decisionos_analytics/evidence.py`: Add support for `evidence_type = "predictive_risk"` and `evidence_type = "survival_curve"`.
- `decisionos_analytics/api.py`: Add `/v1/risk/train`, `/v1/risk/predict`, `/v1/survival/evaluate`, `/v1/forecasting/backtest` endpoints.

---

## 13. Frontend Impact

### Page Updates:
- `apps/web/pages/workflow.vue`: Add "Predictive Risk & Survival" panel with risk distribution table and Kaplan-Meier curve chart.
- `apps/web/pages/monitoring.vue`: Add risk score badge to active episodes.
- `apps/web/pages/forecasts.vue`: Add backtest accuracy metrics (MASE/RMSE) and prediction interval toggle.

### Shared Component:
- `apps/web/components/RiskSurvivalChart.vue` (SVG/Canvas rendering of survival curves and calibration plots).

---

## 14. Data Model Impact

### SQLite Table Schema Additions (`store.py`):

```sql
-- Risk & Survival Models Metadata
CREATE TABLE IF NOT EXISTS risk_model (
    tenant_id TEXT NOT NULL REFERENCES tenant(id),
    id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    model_kind TEXT NOT NULL, -- 'classification_risk' | 'survival_cox'
    target_concept TEXT NOT NULL, -- e.g. 'sla_breach_24h'
    parameters_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL, -- brier_score, auc_roc, mase, etc.
    trained_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id)
);

-- Case Risk Scores Cache / Persistence
CREATE TABLE IF NOT EXISTS case_risk_score (
    tenant_id TEXT NOT NULL REFERENCES tenant(id),
    model_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    risk_score REAL NOT NULL, -- 0.0 to 1.0
    risk_tier TEXT NOT NULL, -- 'low' | 'medium' | 'high' | 'critical'
    top_factors_json TEXT NOT NULL,
    calculated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, model_id, case_id)
);
```

---

## 15. Security & Tenancy

- **Tenant Isolation**: Every `risk_model` and `case_risk_score` row requires `(tenant_id, id)`.
- **Query Scoping**: Training and prediction functions strictly filter dataset records by `tenant_id`.
- **Non-Disclosing 404 Contract**: Requesting a `risk_model` or prediction for a resource belonging to another tenant returns `HTTP 404 Not Found`.

---

## 16. Analytical Validity

1. **Classification Risk Baseline**:
   - Must compare model against baseline majority class and naive heuristic.
   - Requires probability calibration check (Brier Score $\le 0.15$, Platt/Isotonic calibration).
   - Requires explicit abstention when input data falls outside trained feature bounds.
2. **Survival Analysis Censoring**:
   - Incomplete open workflow cases must be treated as right-censored observations (Kaplan-Meier estimator handling).
   - Median time-to-breach must include 95% confidence intervals.
3. **Forecasting Hold-out Cross-Validation**:
   - Minimum 3 temporal rolling folds. MASE calculation normalized by in-sample naive forecast error.

---

## 17. Test Strategy

1. **Unit Tests (`tests/test_risk.py`)**:
   - Classifier training, risk score generation, Brier score calculation, survival Kaplan-Meier estimation.
2. **Integration Tests (`tests/test_risk_api.py`)**:
   - API endpoints `/v1/risk/predict`, `/v1/survival/evaluate`, `/v1/forecasting/backtest`.
3. **Tenant Isolation Tests (`tests/test_tenant_security_risk.py`)**:
   - Assert Tenant Alpha cannot access or train on Tenant Beta models/scores.
4. **Evidence Binding Tests**:
   - Capture predictive risk evidence artifact and bind to a decision.

---

## 18. Acceptance Criteria

- **AC-01 (Risk Model Training)**: Given an ingested event log (`workflow.py`), POST `/v1/risk/train` trains a calibrated classifier and returns model ID with Brier score $\le 0.20$.
- **AC-02 (Case Risk Scoring)**: POST `/v1/risk/predict` accepts active case IDs and returns probabilities (0.0 to 1.0), risk tiers, and top 3 risk drivers.
- **AC-03 (Survival Projection)**: POST `/v1/survival/evaluate` computes Kaplan-Meier survival curves and estimates median remaining time to case resolution with right-censored handling.
- **AC-04 (Forecasting Fold Evaluation)**: POST `/v1/forecasting/backtest` executes 3-fold rolling temporal cross-validation and returns MASE metric and 80%/95% prediction intervals.
- **AC-05 (Evidence Capture & Proactive Investigation)**: Capturing risk prediction creates an immutable `evidence_artifact` (`evidence_type = "predictive_risk"`), which can be attached to a proactive investigation.
- **AC-06 (Tenant Security)**: Accessing risk models across tenant boundaries returns HTTP 404 Not Found without side effects.
- **AC-07 (Quality Gates)**: 100% test pass rate, $\ge 90.00\%$ total coverage, 0 TypeScript errors, clean build.

---

## 19. Ordered Work Packages

### **WP-01: Risk & Survival Mathematical Foundation (`risk.py`)**
- **Goal**: Implement classifier training, Platt calibration, Kaplan-Meier estimator, and Cox regression helpers in `risk.py`.
- **Dependencies**: `workflow.py`, `semantics.py`.
- **Completion Evidence**: `tests/test_risk.py` PASS with 100% unit coverage on mathematical routines.

### **WP-02: Persistence & Evidence Integration**
- **Goal**: Add SQLite tables `risk_model` and `case_risk_score` to `store.py`. Enable evidence serialization (`evidence.py`) for predictive risk and survival curves.
- **Dependencies**: WP-01.
- **Completion Evidence**: Database foreign keys verified, evidence artifacts created and digest-verified.

### **WP-03: Risk & Survival API Endpoints (`api.py`)**
- **Goal**: Implement `/v1/risk/train`, `/v1/risk/predict`, `/v1/survival/evaluate`, `/v1/forecasting/backtest`.
- **Dependencies**: WP-02.
- **Completion Evidence**: `tests/test_risk_api.py` and `tests/test_tenant_security_risk.py` PASS with non-disclosing 404 checks.

### **WP-04: Frontend Risk & Survival Experience (`workflow.vue` & `monitoring.vue`)**
- **Goal**: Add predictive risk scores, survival curve charts, and "Launch Proactive Investigation" actions to `workflow.vue` and `monitoring.vue`.
- **Dependencies**: WP-03.
- **Completion Evidence**: `npm run typecheck` and `npm run build` PASS.

### **WP-05: End-to-End Proactive Decision Loop Certification**
- **Goal**: Certify complete journey from predictive risk alert → proactive investigation → evidence artifact → decision brief → decision register.
- **Dependencies**: WP-04.
- **Completion Evidence**: E2E test suite PASS, total coverage $\ge 90.00\%$, full phase certification report.

---

## 20. Risks & Mitigation

| Risk | Impact | Mitigation Strategy |
|---|---|---|
| Uncalibrated risk scores cause false alarms | High | Mandatory Brier score threshold and Platt/Isotonic calibration check before model is marked active. |
| Incomplete workflow cases distort survival estimates | Medium | Strictly use Kaplan-Meier right-censoring for open/active cases. |
| Overfitting on small dataset revisions | Medium | Enforce minimum case count threshold (>= 30 cases) before enabling predictive risk modeling. |

---

## 21. Dependencies & Open Questions

- **Open Question 1**: Should default risk tier thresholds be configurable per alert rule or global per tenant? *(Recommendation: Tenant default with rule-level override capability).*
- **Dependency**: Uses existing PM4Py event log parsing in `workflow.py`.

---

## 22. Definition of Done

1. Work Packages WP-01 through WP-05 implemented and merged to `main`.
2. All backend tests pass 100% across 3 consecutive runs.
3. Total backend coverage $\ge 90.00\%$.
4. Frontend `npm run typecheck` and `npm run build` exit code 0.
5. Database foreign keys and integrity check pass with 0 orphans.
6. Independent certification report approved.

---

NEXT PHASE:
D3-A: Predictive Risk & Operational Forecasting

WHY NOW:
D2 established the operational decision loop, but it is currently 100% reactive (investigations trigger only after SLA breaches occur). Adding Classification Risk Scoring and Survival Backlog Projection transforms DecisionOS into a proactive platform that predicts breaches and enables proactive decision-making before failures happen, directly fulfilling Stage D3 of the Master Specification.

FIRST WORK PACKAGE:
WP-01: Risk & Survival Mathematical Foundation (risk.py)

IMPLEMENTATION STATUS:
PLANNING ONLY — DO NOT CODE
