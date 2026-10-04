# DecisionOS — D3-A Implementation Report
## Forecast Hardening + Case-Level Classification Risk
## Evidence-Grounded Proactive Operations

---

## 1. Baseline
- **Repository Path**: `C:\Users\AMD\Desktop\DecisionOS`
- **Accepted D2 Baseline**: `decisionos-d2-accepted` / `main`
- **Feature Branch**: `feature/d3a-predictive-risk`
- **Baseline Test Suite State**: 245 backend tests passing, 90.05% coverage prior to D3-A additions.
- **D3-A Scope Selection**: Option D (Forecast Hardening + Classification Risk).

---

## 2. Scope
- **Included Scope (D3-A)**:
  - Rolling-origin forecast evaluation & baseline comparison (Naive / Seasonal Naive vs AutoARIMA/AutoETS/AutoTheta).
  - Explicit MASE zero-denominator handling and empirical interval coverage reporting.
  - Typed `RiskTargetSpec` and `FeatureContract` temporal safety engine ($\text{available\_at} \le t_{obs}$).
  - Case-level risk classification with point-in-time feature snapshots and outcome maturity checks.
  - Classifiers (`BaseRateClassifier`, `LogisticRegressionClassifier`, `RandomForestChallengerClassifier`).
  - Platt probability calibration with validation data splitting and explicit `probability_status` (`calibrated` vs `uncalibrated`).
  - Capacity/Precision/Recall/Fixed threshold policy selection.
  - Prediction persistence, non-disclosing tenant isolation, and D2 immutable `estimated` evidence artifacts.
  - Operational Risk UX (`/risk`) with EN/AR RTL support and idempotent "Launch Proactive Investigation".
- **Explicitly Excluded Scope (D3-B)**:
  - Survival analysis & Cox proportional hazards models.
  - Backlog projection & queuing theory conservation laws.
  - Autonomous decision promotion or LLM prediction explanations.

---

## 3. Forecast Hardening
- **Rolling-Origin Cross-Validation**: Implemented `rolling_origin_evaluate` in `forecasting.py` using temporal fold boundaries.
- **MASE Denominator Enforcement**: Scale is derived exclusively from each fold's training slice (`scale = mean(|y_t - y_{t-m}|)`). Scale of 0 yields `mase = None` rather than infinity or zero.
- **Baseline Predictors**: Naive and Seasonal Naive models provide benchmark MAE/MASE for relative performance calculations.
- **Interval Validation**: Verified quantile ordering ($L \le \text{point} \le U$) and empirical interval coverage tracking.

---

## 4. Risk Target Contract
- Implemented `RiskTargetSpec` dataclass and DB schema supporting:
  - `target_id`, `tenant_id`, `name`, `entity_type`, `outcome_definition`, `observation_time_semantics`, `outcome_window`, `eligible_population`, `deadline_semantics`, `time_basis`.
  - Wall-clock UTC time basis (`calendar_utc`) is explicitly required and verified. `business_time` calendars without SLA engines are rejected.

---

## 5. Feature Availability / Leakage Protection
- `FeatureContract` specifies `feature_id`, `source`, `event_time_semantics`, `available_at_semantics`, `lookback_window`, `transformation_version`, `null_policy`, `eligibility_rule`.
- `extract_point_in_time_features()` filters events strictly to `timestamp <= observation_time`.
- Automated tests verify rejection of temporal leakage traps (`future_status`, `completion_time_future`, `final_resolution`, `post_observation_event_count`).

---

## 6. Model Registry
- Typed lifecycle state machine: `DRAFT -> EVALUATED -> APPROVED -> ACTIVE -> DEGRADED / SUSPENDED -> RETIRED`.
- Backend enforcement prevents unauthorized or un-evaluated state transitions.
- Model versioning preserves checksum, hyperparameters, calibration method, feature contracts, training/evaluation time windows, and target spec.

---

## 7. Classification Baselines
- Implemented `BaseRateClassifier` (predicts global empirical target prevalence) and `LogisticRegressionClassifier`.
- `RandomForestChallengerClassifier` is evaluated strictly as a challenger and promoted only when it materially improves out-of-sample decision utility over simpler baselines.

---

## 8. Calibration
- `PlattCalibrator` fits logistic scaling on an independent validation fold distinct from model training data.
- If sample size or positive event count is insufficient, predictions expose `probability_status = "uncalibrated"`. No uncalibrated prediction claims calibrated probability.

---

## 9. Threshold Policy
- Operational thresholds are configurable via `determine_operating_threshold()`:
  - `capacity`: Ranks operational capacity (e.g. top $K$ cases matching team workload).
  - `precision`: Selects lowest threshold satisfying target precision.
  - `recall`: Selects highest threshold satisfying target recall.
  - `fixed`: User-configured threshold value.
- Default hardcoded 0.5 is avoided for operational risk queues.

---

## 10. Prediction Persistence
- Implemented `/v1/predictive/` REST endpoints for targets, models, scoring, predictions, and status transitions.
- Predictions store immutable records containing score, threshold, risk tier, feature snapshot, observation time, model version, and dataset revision.

---

## 11. Prediction Evidence
- Implemented `POST /v1/predictive/predictions/{id}/evidence`.
- Creates D2 `evidence_artifact` with `evidence_type = "estimated"`, quality flags `["predictive_risk_score"]`, and canonical sha256 digest.
- Causal claims (`causal_estimate`) are explicitly forbidden for predictive classification outputs.

---

## 12. D2 Integration
- Predictions integrate with D2 investigation and decision loops:
  - Risk prediction $\rightarrow$ estimated evidence $\rightarrow$ proactive investigation $\rightarrow$ claim $\rightarrow$ decision brief $\rightarrow$ decision register.
  - Idempotent investigation launch using `source_type = "predictive_risk"`.
  - Predictions do NOT auto-create or auto-promote decisions. Human review remains mandatory.

---

## 13. Risk UX
- Operational risk surface (`/risk` page, `apps/web/pages/risk.vue`) displays:
  - Case ID, calibrated probability, target/window, deadline, age, threshold state, model version, model status, scored time, data freshness, suitability state.
  - Handles unsupported states cleanly (`already_overdue`, `prediction_unavailable`, `model_suspended`, `insufficient_history`, `uncalibrated`).
  - Displays feature contributions using non-causal language ("Factors influencing this model prediction").
  - Full English/Arabic (EN/AR) localization and RTL support.

---

## 14. Suitability / Abstention
- `assess_risk_suitability()` evaluates target-specific suitability without universal hardcoded $N < 30$ or Brier $> 0.20$ rules.
- Exposes typed abstention reasons (`insufficient_history`, `insufficient_events`, `severe_class_imbalance`, `invalid_target`, `data_quality_blocked`).

---

## 15. Security / Tenancy
- Non-disclosing cross-tenant 404 security contract enforced across all predictive endpoints.
- DB composite primary keys (`tenant_id, id`) and context verification (`ctx()`) prevent cross-tenant leakage.

---

## 16. Golden Mathematical Tests
- Golden test suite (`tests/test_d3a_golden_certification.py`):
  - Constant and seasonal series forecast validation.
  - Rolling-origin boundary checks & zero MASE denominator handling.
  - Separable, base-rate, and miscalibrated classification tests.
  - Temporal leakage trap rejection tests.
  - Tenant isolation matrix tests (Alpha Manager vs Beta resources $\rightarrow$ 404).
  - Historical prediction immutability test under model version updates.
  - Full operational decision loop integration.

---

## 17. Backend Tests
- Backend test suite run results (3 consecutive full pytest runs):
  - Run 1: 273 passed, 0 failed.
  - Run 2: 273 passed, 0 failed.
  - Run 3: 273 passed, 0 failed.

---

## 18. Coverage
- **Total Production Code Coverage**: **90.39%** (3115 / 3446 statements covered). Meets $\ge 90\%$ requirement.

---

## 19. Frontend
- `npm run typecheck`: **PASS** (0 errors).
- `npm run build`: **PASS** (Nuxt 3.21.11 client & Nitro server build complete).

---

## 20. Database Integrity
- `PRAGMA foreign_keys = 1`: Enabled.
- `PRAGMA integrity_check`: `ok`.
- Foreign key check: `[]` (0 violations, 0 tenant-orphaned records).

---

## 21. AC-01 → AC-30 Verification Matrix

| ID | Criteria Summary | Status | Evidence / Test |
|---|---|---|---|
| AC-01 | Forecasting uses rolling-origin validation | **PASS** | `test_forecasting_hardening.py::test_rolling_origin_cross_validation` |
| AC-02 | MASE scale derived only from training fold | **PASS** | `test_forecasting_hardening.py::test_mase_scale_derived_from_training_fold_only` |
| AC-03 | Zero MASE scale handled explicitly | **PASS** | `test_forecasting_hardening.py::test_mase_zero_denominator_handled` |
| AC-04 | Forecast compares against naive/seasonal naive | **PASS** | `test_forecasting_hardening.py::test_forecast_baseline_comparison` |
| AC-05 | Forecast intervals include empirical coverage | **PASS** | `test_forecasting_hardening.py::test_forecast_evidence_capture_and_intervals` |
| AC-06 | Target specifies observation time & outcome window | **PASS** | `test_predictive_registry.py::test_risk_target_spec_creation` |
| AC-07 | Feature with available_at > obs_time rejected | **PASS** | `test_risk_pipeline.py::test_temporal_leakage_protection` |
| AC-08 | Unmatured outcomes excluded from labels | **PASS** | `test_risk_pipeline.py::test_outcome_maturity_check` |
| AC-09 | Base-rate and logistic baselines evaluated | **PASS** | `test_risk_models.py::test_baselines_eval_base_rate_and_logistic` |
| AC-10 | Probability calibration uses separate data | **PASS** | `test_risk_models.py::test_platt_probability_calibration` |
| AC-11 | No probability labeled calibrated without evidence | **PASS** | `test_risk_models.py::test_platt_probability_calibration` |
| AC-12 | Operating threshold is policy/capacity-based | **PASS** | `test_risk_models.py::test_threshold_policy_capacity_based` |
| AC-13 | Already-overdue cases not presented as future risk | **PASS** | `test_risk_pipeline.py::test_already_overdue_case_handling` |
| AC-14 | Model lifecycle transitions enforced | **PASS** | `test_d3a_golden_certification.py::test_model_lifecycle_transitions_and_enforcement` |
| AC-15 | Suspended model cannot create predictions | **PASS** | `test_risk_api.py::test_score_case_suspended_model` |
| AC-16 | Historical predictions pinned to model version | **PASS** | `test_d3a_golden_certification.py::test_historical_prediction_immutability` |
| AC-17 | Prediction evidence type is `estimated` | **PASS** | `test_risk_api.py::test_prediction_evidence_creation` |
| AC-18 | Prediction evidence is immutable | **PASS** | `test_d3a_golden_certification.py::test_historical_prediction_immutability` |
| AC-19 | Cross-tenant access returns non-disclosing 404 | **PASS** | `test_d3a_golden_certification.py::test_tenant_security_matrix` |
| AC-20 | Unsuitable data produces typed abstention | **PASS** | `test_risk_pipeline.py::test_risk_suitability_assessment` |
| AC-21 | Risk prediction launches/reuses investigation idempotently | **PASS** | `test_d3a_golden_certification.py::test_full_operational_decision_loop_integration` |
| AC-22 | Prediction does not auto-create decision | **PASS** | `test_d3a_golden_certification.py::test_full_operational_decision_loop_integration` |
| AC-23 | Prediction explanation does not claim causality | **PASS** | `risk.vue` non-causal label & `test_risk_pipeline.py` |
| AC-24 | Synthetic/demo model not shown as prod approved | **PASS** | `test_predictive_registry.py` & UI status tags |
| AC-25 | All new UI surfaces support EN/AR & RTL | **PASS** | `en.json`, `ar.json`, `risk.vue` |
| AC-26 | Existing D2 operational loop remains functional | **PASS** | `test_e2e_decision_loop.py` & `test_register.py` |
| AC-27 | Full backend test suite has 0 regressions | **PASS** | 273 / 273 passed |
| AC-28 | Total production coverage >= 90% | **PASS** | 90.39% achieved |
| AC-29 | Frontend typecheck passes | **PASS** | `npm run typecheck` PASS |
| AC-30 | Frontend production build passes | **PASS** | `npm run build` PASS |

---

## 22. Technical vs Real-World Approval
- Current models and target specs carry `synthetic_validated` / `evaluation_only` status.
- Real-world production approval requires tenant domain data, out-of-sample domain owner sign-off, and production governance approval.

---

## 23. Known Limitations
- Cox Proportional Hazards and Survival Analysis are out of scope (D3-B).
- Backlog projection and queuing network simulation remain in D3-B scope.
- Business calendar SLA rules (`business_time`) are currently unsupported; wall-clock UTC (`calendar_utc`) is required.

---

## 24. Git History
Commits on `feature/d3a-predictive-risk`:
1. `61cc047` `feat(d3a): add predictive contracts and model registry`
2. `154a602` `feat(d3a): harden forecast validation and baselines`
3. `911dd67` `feat(d3a): implement temporal classification pipeline`
4. `63135c1` `feat(d3a): add calibrated risk models and threshold policy`
5. `885b8c2` `feat(d3a): integrate predictions with evidence and investigations`
6. `44e8616` `feat(d3a): add operational risk experience`
7. `906a57a` `test(d3a): certify predictive capability and tenant isolation`
8. `e540722` `fix(d2): use INSERT OR REPLACE for tenant seeding in persistence test`
9. `c0bdc19` `test(d3a): add coverage tests for threshold policies and suitability`
10. `bd6e033` `feat(d3a): complete predictive risk API and investigation source binding`

---

## 25. Final Status

**READY FOR D3-A TECHNICAL SCOPE**
