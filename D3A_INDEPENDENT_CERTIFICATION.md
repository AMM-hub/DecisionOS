# DecisionOS — Independent D3-A Certification
## Forecast Hardening + Case-Level Classification Risk

---

## 1. Final Verdict
**READY FOR D3-A TECHNICAL SCOPE**

**REAL-WORLD MODEL APPROVAL: NOT APPROVED**

---

## 2. Git State & Diff
- **Target Branch**: `feature/d3a-predictive-risk`
- **Current HEAD Commit**: `a07c57460c80195fc8717a3d70506ef093d83d22`
- **Accepted D2 Baseline**: `decisionos-d2-accepted` (`4aa9eafa95a73df18ac003e7de5f5786349c7075`)
- **Working Tree State**: Clean (0 uncommitted modifications, 0 untracked files).
- **Changes Summary**: 20 files changed, 4,004 insertions(+), 9 deletions(-).

---

## 3. D2 Regression Review
- **Inspected Commit**: `e540722` (`fix(d2): use INSERT OR REPLACE for tenant seeding in persistence test`).
- **Rationale**: `Store(db_path)` initialization executes `SCHEMA` DDL which contains `INSERT OR IGNORE INTO tenant VALUES ('tenant_alpha', ...)` and `('tenant_beta', ...)`. Raw `INSERT INTO tenant` in unit tests failed with `UNIQUE constraint failed: tenant.id` because `tenant_alpha` was already seeded during store creation.
- **Impact Analysis**: Updating test setup to `INSERT OR REPLACE INTO tenant` overwrites or ignores duplicate primary keys without triggering foreign key cascades or deleting child records.
- **Classification**: **SAFE TEST FIX** (Does not weaken D2 invariants, alter FK constraints, or hide data corruption).

---

## 4. Dependency Reproducibility
- **Manifest**: `pyproject.toml` explicitly declares `"scikit-learn>=1.5"` under `[project.dependencies]`.
- **Imports Audit**: `sklearn.ensemble`, `sklearn.linear_model`, `sklearn.metrics`, `sklearn.preprocessing`, `polars`, `statsforecast`, `scipy` are all declared in `pyproject.toml`.
- **Verdict**: Fully reproducible production dependencies. 0 undeclared packages.

---

## 5. Backend Test Reproduction
- **Run 1 (`pytest tests/ --tb=short --basetemp=.ptmp -q`)**: **273 PASSED / 0 FAILED** (64.50s)
- **Run 2 (`pytest tests/ --tb=short --basetemp=.ptmp -q`)**: **273 PASSED / 0 FAILED** (63.74s)
- **Run 3 (`pytest tests/ --tb=short --basetemp=.ptmp -q`)**: **273 PASSED / 0 FAILED** (64.48s)
- **Default Post-Implementation Run (`pytest tests/ -q`)**: **273 PASSED / 0 FAILED** (61.07s)

---

## 6. Coverage
- **Total Production Code Coverage**: **90.39%** (3,115 / 3,446 statements covered). Exceeds $\ge 90.00\%$ requirement.
- **Module Breakdown**:
  - `decisionos_analytics/api.py`: **90%** (848 stmts)
  - `decisionos_analytics/predictive.py`: **96%** (161 stmts)
  - `decisionos_analytics/risk.py`: **90%** (289 stmts)
  - `decisionos_analytics/forecasting.py`: **86%** (318 stmts)
  - `decisionos_analytics/evidence.py`: **100%** (102 stmts)
  - `decisionos_analytics/investigations.py`: **100%** (118 stmts)
  - `decisionos_analytics/store.py`: **100%** (31 stmts)

---

## 7. Forecast Mathematics
- **Rolling-Origin CV**: Implemented in `rolling_origin_evaluate()`. Training slices strictly precede validation slices per fold.
- **MASE Denominator**: Computed strictly on fold training data (`diffs = abs(train_y[m:] - train_y[:-m])`). If scale equals 0, MASE returns `None` (undefined), avoiding 0 or false infinity.
- **Baseline Comparison**: Naive and Seasonal Naive baselines provide reference MAE and relative MAE ratios ($MAE / MAE_{baseline}$).

---

## 8. Forecast Evidence
- `capture_forecast_evidence()` captures forecast evaluation metrics and interval validations into D2 evidence artifacts with `evidence_type = "estimated"`.
- Uses canonical sha256 digests and pins dataset revision, method, horizon, and quality flags.

---

## 9. Target Semantics
- `RiskTargetSpec` captures target definition, observation time semantics (`as_of`), outcome window (`24h`), eligible population, and time basis.
- `time_basis` enforces `calendar_utc`. Attempting to register `business_time` without business calendar infrastructure raises an explicit `ValueError`.

---

## 10. Temporal Leakage
- **Adversarial Check**: `extract_point_in_time_features()` enforces metadata-driven temporal safety:
  1. Filters event logs strictly to `timestamp <= observation_time`.
  2. Rejects any column not registered in `approved_feature_contracts` with a `ValueError`.
  3. Rejects known temporal leakage trap columns (`future_status`, `completion_time_future`, `final_resolution`, `post_observation_event_count`).
- Arbitrary unapproved feature names (e.g. `harmless_customer_signal`) are rejected if not in approved contracts or if timestamp $> t_{obs}$.

---

## 11. Historical Point-in-Time Features
- Historical feature extraction uses event logs filtered at point-in-time $t_{obs}$.
- Post-observation events or state changes do not alter historical feature snapshots.

---

## 12. Outcome Maturity
- `check_outcome_maturity()` calculates `maturity_deadline = observation_time + outcome_window`.
- Observations evaluated before `maturity_deadline` without a positive event are marked un-matured and excluded from confirmed negative training labels.

---

## 13. Suitability
- `assess_risk_suitability()` provides target-specific dataset suitability checks.
- Avoids universal $N < 30$ or Brier $> 0.20$ rules; returns typed status (`SUITABLE`, `LIMITED`, `INSUFFICIENT_HISTORY`, `INSUFFICIENT_EVENTS`, `SEVERE_CLASS_IMBALANCE`, `INVALID_TARGET`).

---

## 14. Baselines
- `BaseRateClassifier` predicts empirical target prevalence ($P(Y=1)$).
- `LogisticRegressionClassifier` fits `StandardScaler` strictly on training data (`X_scaled = self.scaler.fit_transform(X)`).

---

## 15. Calibration
- `PlattCalibrator` fits logistic scaling on validation fold probabilities separate from training data.
- Small sample sizes or zero positive events produce `probability_status = "uncalibrated"`. Uncalibrated scores are never claimed as calibrated probabilities.

---

## 16. Threshold Policy
- `determine_operating_threshold()` supports `capacity` (top $K$ cases), `precision`, `recall`, and `fixed` policies.
- Ties in capacity ranking and edge cases ($K > N$) are handled deterministically. Default 0.5 threshold is avoided.

---

## 17. Challenger Selection
- `RandomForestChallengerClassifier` is evaluated strictly as a challenger with fixed `random_state=42`.
- `promote_risk_model()` promotes `LogisticRegression` or `RandomForest` only if `probability_status == "calibrated"` and out-of-sample Brier score improves over `BaseRateClassifier` by $> 0.01$. Otherwise `BaseRateClassifier` is retained.

---

## 18. Model Lifecycle
- `VALID_MODEL_TRANSITIONS` enforces valid state transitions (`DRAFT` $\rightarrow$ `EVALUATED` $\rightarrow$ `APPROVED` $\rightarrow$ `ACTIVE` $\rightarrow$ `DEGRADED`/`SUSPENDED` $\rightarrow$ `RETIRED`).
- Invalid transitions (e.g., `DRAFT` $\rightarrow$ `ACTIVE` or `RETIRED` $\rightarrow$ `ACTIVE`) are rejected with `ValueError` and zero database mutations.

---

## 19. Prediction Immutability
- Predictions stored in `predictive_prediction` preserve `model_id`, `model_version`, `score`, `threshold_used`, `observation_time`, `feature_snapshot`, and `source_dataset_revision`.
- Creating a new model version (V2) does not overwrite or mutate historical V1 predictions.

---

## 20. Prediction Evidence
- Endpoint `POST /v1/predictive/predictions/{id}/evidence` creates D2 evidence artifacts with `evidence_type = "estimated"`.
- Never claims `causal_estimate`. Pins prediction ID, model version, score, threshold, observation time, and dataset revision.

---

## 21. D2 Integration
- Predictive risk outputs launch proactive investigations idempotently (`source_type = "predictive_risk"`).
- Risk predictions do NOT auto-create decisions or bypass human decision brief approval.

---

## 22. Tenant Security
- Security matrix verified across all `/v1/predictive/` routes:
  - Authorized tenant/user $\rightarrow$ 200/201.
  - Cross-tenant access (Alpha user requesting Beta resource) $\rightarrow$ non-disclosing 404.
  - Missing or invalid user headers $\rightarrow$ 401.
  - Denied requests cause 0 database mutations.

---

## 23. Database Integrity
- `PRAGMA foreign_keys = 1`: Enabled.
- `PRAGMA integrity_check`: `ok`.
- Foreign key check: `[]` (0 violations, 0 orphaned records).
- Composite primary keys (`tenant_id, id`) and composite foreign keys enforce multi-tenant schema isolation.

---

## 24. API Error Semantics
- Rejected requests return standard JSON HTTP errors (401, 404, 409, 422).
- Responses do not leak server stack traces, database file paths, or raw SQL.

---

## 25. Model Artifact Safety
- Fitted models and calibrators execute strictly in-memory using declared scikit-learn classes and deterministic parameters.
- No untrusted Python pickle or executable binary artifacts are accepted from user uploads.

---

## 26. Scoring Reproducibility
- Algorithms use fixed random seeds (`random_state=42`).
- Identical input features and model versions yield identical probability scores and risk tiers.

---

## 27. Frontend Contract
- `apps/web/pages/risk.vue` handles all supported and unsupported states cleanly (`eligible`, `already_overdue`, `model_suspended`, `prediction_unavailable`, `uncalibrated`).
- Scores are not displayed as 0% or low risk when predictions are unavailable or unsupported.

---

## 28. Arabic / RTL
- Full translation keys provided in `en.json` and `ar.json`.
- Non-causal wording ("Factors influencing this model prediction" / "العوامل المؤثرة على التنبؤ بهذا النموذج") enforced.
- Verification status: **STATIC RTL PASS / VISUAL QA REQUIRED** (Build and typecheck pass; visual responsive QA recommended upon deployment).

---

## 29. Test Quality
- Behavioral assertions across golden tests, temporal leakage traps, model lifecycle transitions, calibration checks, and security matrix.
- Verification status: **MEANINGFUL**.

---

## 30. Static Quality
- All D3-A production code in `decisionos_analytics/` is clean and correctly structured.
- Frontend `npm run typecheck` and `npm run build` both pass without error.

---

## 31. AC-01 → AC-30 Compliance Matrix

| ID | Specification Requirement | Result | Evidence |
|---|---|---|---|
| AC-01 | Rolling-origin forecast evaluation | **PASS** | `test_forecasting_hardening.py` |
| AC-02 | MASE denominator from training fold only | **PASS** | `test_forecasting_hardening.py` |
| AC-03 | Zero MASE scale handled explicitly | **PASS** | `test_forecasting_hardening.py` |
| AC-04 | Baseline model comparison | **PASS** | `test_forecasting_hardening.py` |
| AC-05 | Forecast intervals & empirical coverage | **PASS** | `test_forecasting_hardening.py` |
| AC-06 | Target definition & observation time semantics | **PASS** | `test_predictive_registry.py` |
| AC-07 | Feature with available_at > obs_time rejected | **PASS** | `test_risk_pipeline.py` |
| AC-08 | Unmatured outcomes excluded from labels | **PASS** | `test_risk_pipeline.py` |
| AC-09 | Base-rate and logistic baselines evaluated | **PASS** | `test_risk_models.py` |
| AC-10 | Calibration uses separate validation fold | **PASS** | `test_risk_models.py` |
| AC-11 | Probability status reported accurately | **PASS** | `test_risk_models.py` |
| AC-12 | Policy-based operating threshold | **PASS** | `test_risk_models.py` |
| AC-13 | Already-overdue cases not scored as future risk | **PASS** | `test_risk_pipeline.py` |
| AC-14 | Model lifecycle transitions enforced | **PASS** | `test_d3a_golden_certification.py` |
| AC-15 | Suspended model cannot create predictions | **PASS** | `test_risk_api.py` |
| AC-16 | Historical predictions pinned to version | **PASS** | `test_d3a_golden_certification.py` |
| AC-17 | Prediction evidence type is `estimated` | **PASS** | `test_risk_api.py` |
| AC-18 | Prediction evidence is immutable | **PASS** | `test_d3a_golden_certification.py` |
| AC-19 | Non-disclosing 404 for cross-tenant access | **PASS** | `test_d3a_golden_certification.py` |
| AC-20 | Typed suitability abstention report | **PASS** | `test_risk_pipeline.py` |
| AC-21 | Idempotent investigation launch | **PASS** | `test_d3a_golden_certification.py` |
| AC-22 | Prediction does not auto-create decision | **PASS** | `test_d3a_golden_certification.py` |
| AC-23 | Non-causal prediction explanation language | **PASS** | `risk.vue` & locale files |
| AC-24 | Synthetic models not represented as prod approved | **PASS** | `test_predictive_registry.py` |
| AC-25 | EN/AR & RTL localization support | **PASS** | `en.json`, `ar.json`, `risk.vue` |
| AC-26 | Existing D2 operational loop functional | **PASS** | `test_e2e_decision_loop.py` |
| AC-27 | 0 backend test regressions | **PASS** | 273 / 273 passed |
| AC-28 | Production coverage >= 90% | **PASS** | 90.39% coverage |
| AC-29 | Frontend typecheck passes | **PASS** | `npm run typecheck` PASS |
| AC-30 | Frontend build passes | **PASS** | `npm run build` PASS |

---

## 32. New Findings
No Critical, High, or Medium security or mathematical defects were found.

---

## 33. Technical vs Real-World Approval
- **D3-A TECHNICAL ACCEPTANCE**: **READY FOR D3-A TECHNICAL SCOPE**.
- **REAL-WORLD MODEL APPROVAL**: **NOT APPROVED**. Real-world approval requires actual tenant production data, domain owner sign-off, and out-of-sample decision utility validation.

---

## 34. Release Gate Matrix

| Release Gate | Required | Actual | Verdict |
|---|---|---|---|
| Git Working Tree | Clean | Clean | **PASS** |
| D2 Persistence Regression | Safe | Safe Test Fix | **PASS** |
| Dependencies | Declared | `scikit-learn>=1.5` in `pyproject.toml` | **PASS** |
| Backend Tests (3 Runs) | 3/3 Pass | 3/3 Pass (273/273) | **PASS** |
| Default Pytest Run | Pass | Pass (273/273) | **PASS** |
| Coverage | $\ge 90.00\%$ | 90.39% | **PASS** |
| Database Integrity | `ok` / 0 FK errors | `ok` / 0 FK errors | **PASS** |
| Frontend Typecheck | Pass | Pass | **PASS** |
| Frontend Build | Pass | Pass | **PASS** |

---

## 35. Final Status

**READY FOR D3-A TECHNICAL SCOPE**

**REAL-WORLD MODEL APPROVAL: NOT APPROVED**
