# DecisionOS — D3-A Architecture Freeze

## 1. Accepted Baseline

- **Repository**: `C:\Users\AMD\Desktop\DecisionOS`
- **Branch**: `main`
- **Accepted Baseline Tag**: `decisionos-d2-accepted`
- **Accepted Commit**: `4aa9eafa95a73df18ac003e7de5f5786349c7075`
- **Quality Baseline**: 245 backend tests passing, 90.05% total production coverage, 0 TypeScript errors, clean Nuxt build, zero database integrity errors, non-disclosing 404 security contract.
- **Planning Mode Constraint**: READ-ONLY planning gate. Zero production code files, migrations, API endpoints, or frontend pages created during this task.

---

## 2. Existing Predictive Capability

Inspection of the `main` repository reveals the following existing predictive infrastructure:

- **Implemented**: Aggregate Time-Series Forecasting ([forecasting.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/forecasting.py), [forecasts.vue](file:///C:/Users/AMD/Desktop/DecisionOS/apps/web/pages/forecasts.vue)). Supports ARIMA and ExponentialSmoothing models with 80%/95% prediction intervals and single-split evaluation metrics (MAE, RMSE, MAPE).
- **Implemented**: Contextual Alert Monitoring ([monitoring.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/monitoring.py), [monitoring.vue](file:///C:/Users/AMD/Desktop/DecisionOS/apps/web/pages/monitoring.vue)). Triggers episode alerts when metrics breach static threshold conditions.
- **Implemented**: Workflow Event Log Analysis ([workflow.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/workflow.py), [workflow.vue](file:///C:/Users/AMD/Desktop/DecisionOS/apps/web/pages/workflow.vue)). Parses PM4Py logs, extracts case variants, bottleneck activities, and open case durations.
- **Missing**: Case-level classification risk scoring, probability calibration, survival time-to-breach estimation, stock-flow backlog projection, rolling-origin forecast cross-validation, and evidence artifact persistence for predictive outputs.

---

## 3. Corrected Product Gap

DecisionOS is **NOT 100% reactive** today because aggregate time-series forecasting already exists. However, its **operational workflow monitoring is reactive**:

1. **Aggregate vs Case Level**: `forecasting.py` predicts macro volume trends (e.g. total ticket volume next week), but cannot evaluate case-level risk for specific open workflow tickets.
2. **Pre-Breach vs Post-Breach**: `monitoring.py` triggers episodes *after* a metric or SLA threshold has already breached.
3. **Targeted Remediation Gap**: Operators cannot identify which specific active cases are at highest probability of SLA breach before the breach occurs.

---

## 4. W17 / W18 / W19 Gap Analysis

| Specification Package | Capability Item | Status | Current Code Base State |
|---|---|---|---|
| **W17 — Forecasting Hardening** | Naive & Seasonal Naive Baselines | PARTIAL | Basic mean fallback in `forecasting.py`; formal Naive/S-Naive benchmark models missing. |
| | Rolling-Origin Cross-Validation | MISSING | Single train/test split only; no expanding/sliding window temporal CV. |
| | MASE Metric Calculation | MISSING | Calculates MAE, RMSE, MAPE; missing MASE scaling by in-sample naive error. |
| | Prediction Interval Coverage | PARTIAL | Calculates theoretical intervals; missing empirical coverage verification. |
| | Forecast Evidence Persistence | MISSING | Forecast results are ephemeral API responses; not serialized as `evidence_artifact`. |
| **W18 — Classification Risk** | Case Target & Labeling Engine | MISSING | No classification target builder or SLA breach label extractor in codebase. |
| | Observation Time ($t_{obs}$) Filtering | MISSING | No temporal feature extraction windowing or lookback cutoff logic. |
| | Probability Calibration | MISSING | No Platt scaling or Isotonic regression calibration checks. |
| | Capacity-Based Threshold Policy | MISSING | No operational threshold selector based on intervention capacity. |
| **W19 — Survival & Backlog** | Kaplan-Meier & Cox Estimators | MISSING | `workflow.py` calculates mean open case age; missing right-censored survival curves. |
| | Stock-Flow Backlog Conservation | MISSING | No exact inventory conservation solver ($B_t = B_{t-1} + A_t - C_t$). |

---

## 5. Data Readiness Matrix

Evaluation of current SQLite table schemas ([store.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/store.py)) and event log schemas ([workflow.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/workflow.py)):

| Predictive Family | Required Field | Readiness Classification | Repository Source / Detail |
|---|---|---|---|
| **Classification Risk** | `entity_id` | **AVAILABLE** | `case_id` column in `workflow.py` PM4Py event log. |
| | `observation_time` ($t_{obs}$) | **DERIVABLE** | Cutoff timestamp parameter passed to query execution. |
| | `label` ($y_i$) | **DERIVABLE** | `duration > SLA_threshold` or presence of SLA breach event. |
| | `label_available_at` | **DERIVABLE** | `case_end_timestamp` / final event timestamp. |
| | `outcome_window` | **AMBIGUOUS** | Must be explicitly specified in target definition (e.g., 24h). |
| | `eligible_population` | **DERIVABLE** | Filter cases where `case_start <= t_obs` and `case_status == 'open'`. |
| | `SLA / deadline clock` | **MISSING** | Neither `alert_rule` nor `workflow.py` tables store per-case SLA clocks. Must be passed in `RiskTargetSpec`. |
| | `feature timestamps` | **AVAILABLE** | Event `timestamp` column in PM4Py log. |
| **Survival Analysis** | `start_time` / `event_time` | **AVAILABLE** | First and last event timestamps per case in `workflow.py`. |
| | `event_observed` | **DERIVABLE** | `1` if case reached terminal state, `0` if open at $t_{obs}$ (right-censored). |
| | `business-time clocks` | **MISSING** | All durations evaluated in wall-clock UTC; business hours calendar is scaffolded. |
| **Backlog Projection** | `opening_backlog` / `arrivals` | **DERIVABLE** | Active case count and new case starts aggregated per grain window. |
| | `transfers_in` / `transfers_out` | **MISSING** | No multi-queue transfer routing in `workflow.py` schema. |

---

## 6. Initial Prediction Target

To avoid data ambiguity, D3-A defines **exactly ONE initial prediction target**:

- **Subject**: Active event log cases (`case_id` in `workflow.py`).
- **Observation Time ($t_{obs}$)**: Query execution timestamp (`as_of`), or historical cutoff date during backtesting.
- **Eligible Population**: Open cases where `case_start <= t_obs` and `case_status == 'open'` at $t_{obs}$.
- **Target Definition**: Probability that total case duration from start to completion exceeds SLA threshold $H_{SLA}$ hours ($T_{case} > H_{SLA}$).
- **Outcome Window**: $(t_{obs}, t_{obs} + H_{SLA}]$.
- **Deadline Clock**: $d_i = t_{start,i} + H_{SLA}$ (e.g. 24 hours from case creation).
- **Already-Overdue Handling**: Cases where current age $e_i = t_{obs} - t_{start,i} \ge H_{SLA}$ are **EXCLUDED** from binary risk classification (their breach probability is 1.0) and flagged as `already_breached`.
- **Exclusions**: Cases cancelled/abandoned prior to $t_{obs}$.
- **Intervention Opportunity**: Actionable lead time $\Delta t_i = d_i - t_{obs} > 0$ during which operators can re-assign or expedite case $i$.

---

## 7. Feature Availability / Leakage Contract

Every predictive feature $f_k \in X_i(t_{obs})$ constructed at observation time $t_{obs}$ must satisfy the temporal safety invariant:

$$\text{available\_at}(f_k) \le t_{obs}$$

### Enforced Rules:
1. **No Future Events**: Events occurring at $t > t_{obs}$ (future activity names, resolution timestamps, downstream agent assignments) are strictly excluded from the feature matrix.
2. **No Future Revisions**: Datasets and definitions created after $t_{obs}$ cannot be referenced.
3. **Temporal Validation**: Validation must use rolling-origin cross-validation (Time-Series Split / Expanding Window), NOT random train/test splitting.
4. **Leakage Test Trap**: Automated unit test `test_temporal_leakage_rejection` will inject synthetic future event columns (`resolution_timestamp`) and assert the feature compiler raises `FeatureLeakageError`.

---

## 8. Classification Design

- **Baseline Models**:
  1. Base Rate Predictor ($\hat{p} = \bar{y}_{train}$).
  2. Simple Logistic Regression on case age & completed step count.
- **Evaluation Metrics**:
  - **PR-AUC (Precision-Recall Area Under Curve)** as primary metric (handles class imbalance).
  - **Brier Score** ($BS = \frac{1}{N} \sum_{i=1}^N (p_i - y_i)^2$) for probability calibration accuracy.
  - **Platt Scaling / Isotonic Regression** probability calibration checks.
  - Precision, Recall, and Confusion Matrix evaluated at operational threshold $\tau_{op}$.
- **Threshold Policy**: Operational threshold $\tau_{op}$ selected based on operator intervention capacity (e.g. top $K$ highest risk cases capacity), NOT arbitrary 0.5. Probability values will be withheld if Brier score $> 0.20$ or calibration fails.

---

## 9. Model Lifecycle & Metadata

Models are managed as versioned database entities with an explicit lifecycle:

$$\text{draft} \longrightarrow \text{evaluated} \longrightarrow \text{approved} \longrightarrow \text{active} \longrightarrow \text{degraded} \longrightarrow \text{suspended} \longrightarrow \text{retired}$$

### Enforced Model Metadata Schema:
- `tenant_id`, `model_id`, `model_version`, `model_kind` (`classification_risk` | `forecasting_hardened`)
- `target_definition`, `feature_contract_version`, `training_dataset_revision`, `training_window`, `evaluation_window`
- `algorithm`, `hyperparameters`, `calibration_method`, `threshold_policy`
- `metrics_json` (Brier score, PR-AUC, MASE, calibration error)
- `checksum`, `created_at`, `approved_by`, `approved_at`, `status`

Silent retraining and unvetted activation in production are strictly prohibited.

---

## 10. Prediction Evidence Contract

Predictive outputs serialized into `evidence_artifact` ([evidence.py](file:///C:/Users/AMD/Desktop/DecisionOS/services/analytics/decisionos_analytics/evidence.py)) must adhere to the evidence classification rules:

- `evidence_type`: **`estimated`** (NEVER `observed` or `causal_estimate`).
- `support_status`: `supporting` or `counteracting`.
- `exactness_class`: `approximate` / `statistical`.
- `reproducibility_status`: `fully_reproducible` (when pinned to model checksum and feature matrix).

Predictions represent probabilistic estimates and do NOT constitute causal claims or automatic decision commitments.

---

## 11. D2 Integration & Operational Loop

Predictive risk integrates directly into the accepted D2 operational loop:

```
[Active Event Log Case] ──► [Risk Model Evaluates SLA Breach Probability]
                                   │
                                   ▼
          [Risk Evidence Serialized (evidence_type = 'estimated')]
                                   │
                                   ▼
          [Proactive Investigation Created (source = 'predictive_risk')]
                                   │
                                   ▼
          [Decision Brief Drafted & Bound to Risk Evidence]
                                   │
                                   ▼
          [Decision Registered in Decision Register]
```

---

## 12. Suitability & Abstention Engine

Before generating predictions, the system evaluates typed suitability criteria:

- `suitable`: All criteria met.
- `insufficient_history`: Fewer than 30 total cases in training window.
- `insufficient_events`: Fewer than 10 positive SLA breach events.
- `severe_class_imbalance`: Positive class rate $< 2\%$.
- `data_quality_blocked`: Missing or unparseable event timestamps.
- `prediction_unavailable`: System abstains from returning a risk score when suitability is not `suitable`.

---

## 13. Golden Test Corpus

A dedicated synthetic test dataset (`tests/fixtures/risk_golden_dataset.csv`) will be designed containing:

- 2 distinct tenant environments (`tenant_alpha`, `tenant_beta`).
- 200 total cases with known start times, event sequences, completions, right-censored open cases, and relative SLA deadlines.
- Synthetic predictive signals (e.g. cases visiting activity `vendor_escalation` have 85% breach probability).
- Synthetic trap columns (`future_resolution_time`) to verify temporal leakage rejection.

---

## 14. Narrowed D3-A Scope Selection

### **FINAL SELECTED SCOPE**: **Option D — Forecast Hardening + Case-Level Classification Risk**

#### Included Capabilities:
1. **W17 Hardening**: Rolling-origin 3-fold cross-validation, MASE calculation, prediction interval coverage verification, and forecast evidence persistence.
2. **W18 Classification Risk**: Case-level SLA breach risk scoring, Logistic Regression baseline + RandomForest classifier, Platt probability calibration, capacity-based thresholding, and risk evidence binding.
3. **Proactive Investigation Launch**: UI & API support for launching investigations from high-risk active cases.

#### Excluded Scope (Deferred to D3-B / D4):
- Survival / Cox Proportional Hazards models (W19).
- Stock-flow backlog conservation solvers (W19).
- Causal study design & evaluation (W22).
- Governed Action Execution / Webhook dispatch (W24).

---

## 15. Ordered Work Packages

### **WP-01: Forecast Hardening & Evidence Persistence**
- **Goal**: Upgrade `forecasting.py` with rolling-origin cross-validation, MASE metric, prediction interval coverage checks, and evidence artifact persistence.
- **Dependencies**: None (extends existing `forecasting.py`).
- **Completion Evidence**: Unit tests in `test_forecasting.py` verifying MASE calculation, 3-fold temporal CV, and forecast evidence creation.

### **WP-02: Risk Classification & Calibration Engine**
- **Goal**: Implement `decisionos_analytics/risk.py` containing case feature compiler, Logistic/RandomForest classifiers, Platt scaling calibration, and suitability evaluator.
- **Dependencies**: `workflow.py`, `semantics.py`.
- **Completion Evidence**: `tests/test_risk.py` PASS with Brier score and PR-AUC assertions on golden dataset.

### **WP-03: Model Lifecycle & Risk API Endpoints**
- **Goal**: Implement `risk_model` and `case_risk_score` SQLite schema in `store.py`. Add `/v1/risk/train`, `/v1/risk/predict`, `/v1/risk/models` endpoints to `api.py`.
- **Dependencies**: WP-02.
- **Completion Evidence**: `tests/test_risk_api.py` and `tests/test_tenant_security_risk.py` PASS with non-disclosing 404 tenant isolation checks.

### **WP-04: Proactive Risk UX & Proactive Investigation Launch**
- **Goal**: Add "Predictive Risk" drawer to `apps/web/pages/workflow.vue` and enable "Launch Proactive Investigation" from high-risk cases.
- **Dependencies**: WP-03.
- **Completion Evidence**: `npm run typecheck` and `npm run build` PASS with zero errors.

### **WP-05: D3-A Certification & Regression Release Gate**
- **Goal**: Execute complete post-implementation verification (245+ backend tests 100% pass rate, $\ge 90.00\%$ total coverage, database integrity check, clean build).
- **Dependencies**: WP-04.
- **Completion Evidence**: Final D3-A certification report approved.

---

## 16. Technical vs Real-World Release Gate

- **Technical D3-A Acceptance**: Verified via synthetic golden test corpus (`tests/test_risk_golden.py`), 100% test pass rate, $\ge 90.00\%$ total coverage, 0 TypeScript errors, clean build, database integrity.
- **Real-World Model Approval**: Requires live customer event logs, out-of-sample temporal holdout validation, owner review, and operational calibration acceptance before a model can be transitioned to `active` status in production.

---

## 17. Implementation Readiness

READY TO IMPLEMENT
