# DecisionOS — PILOT-01 Controlled Operational Pilot Acceptance Checklist

## Acceptance Matrix

| Item | Requirement | Status | Evidence / Verification |
|---|---|---|---|
| **AC-01** | Pilot resource is tenant-scoped | **PASSED** | Composite PK `(tenant_id, id)` in `store.py` & non-disclosing 404 in `test_pilot_command_center.py` |
| **AC-02** | Pilot cannot become ready without accepted dataset revision | **PASSED** | `validate_pilot_data_readiness` blocks missing/empty datasets |
| **AC-03** | Missing required pilot data blocks readiness | **PASSED** | Returns `BLOCKED` status with missing column reasons |
| **AC-04** | Invalid timestamps/event ordering are surfaced | **PASSED** | `test_data_quality_gate_out_of_order_events` verifies explicit blocked reasons |
| **AC-05** | Dataset refresh creates new revision without overwriting history | **PASSED** | `test_refresh_failure_preserves_previous_revision` verifies revision incrementing |
| **AC-06** | Semantic definitions are versioned/reconstructable | **PASSED** | `SUPPORT_OPERATIONS_SEMANTIC_PACK` has explicit versioning & schema |
| **AC-07** | SLA semantics are explicit | **PASSED** | Target name, eligible population, deadline rule, and calendar_utc configured |
| **AC-08** | Unsupported business-time SLA does not silently use UTC | **PASSED** | Exposes `BUSINESS-TIME SLA NOT SUPPORTED` warning message |
| **AC-09** | Workflow mapping is configurable without source editing | **PASSED** | `POST /v1/pilots/{id}/mapping` API & guided wizard |
| **AC-10** | Monitoring rule can be configured without source editing | **PASSED** | `POST /v1/pilots/{id}/monitoring-rules` API |
| **AC-11** | Risk target can be configured without source editing | **PASSED** | `POST /v1/pilots/{id}/risk-target` API |
| **AC-12** | Synthetic/evaluation model is visibly not real-world approved | **PASSED** | Status explicitly set to `EVALUATION_ONLY` / `NOT_APPROVED_FOR_REAL_WORLD` |
| **AC-13** | Current auth limitation is explicitly classified | **PASSED** | Security status returned as `INTERNAL_EVALUATION_ONLY` |
| **AC-14** | Pilot setup has clear readiness states | **PASSED** | State machine: `draft` $\rightarrow$ `configuration` $\rightarrow$ `ready_for_evaluation` $\rightarrow$ `active` |
| **AC-15** | Bad-data pilot is blocked | **PASSED** | Quality gate returns `BLOCKED` for invalid timestamp/ordering/missing cols |
| **AC-16** | Valid pilot can become ready_for_evaluation | **PASSED** | Verified in `test_pilot_onboarding.py` |
| **AC-17** | Prediction can create/use estimated evidence | **PASSED** | `create_prediction_evidence_api` generates canonical evidence artifact |
| **AC-18** | Alert/risk can launch an investigation | **PASSED** | Verified in `test_pilot_golden_journey.py` |
| **AC-19** | Investigation can support a decision | **PASSED** | Evidence binding connects investigation artifact to decision brief |
| **AC-20** | Accepted decision expectation remains frozen | **PASSED** | `FROZEN_DECISION_STATES` enforces immutability; amendments required for updates |
| **AC-21** | Review due is visible | **PASSED** | Decision state `review_due` surfaced in `/pilot` Command Center & `/decisions` |
| **AC-22** | Outcome recorded with observation window & definitions | **PASSED** | `OutcomeRecord` stores measurement window, baseline, observed, and caveats |
| **AC-23** | Outcome review produces explicit verdict | **PASSED** | `Verdict` enum (`supported_improvement`, `no_clear_change`, `deterioration`, etc.) |
| **AC-24** | Review does not imply causality automatically | **PASSED** | Outcome UI & API preserve descriptive correlation without manufacturing causal claims |
| **AC-25** | Pilot command center uses existing trusted calculations | **PASSED** | `/v1/pilots/{id}/summary` aggregates existing store entities without duplicating engines |
| **AC-26** | Pilot command center links to source records | **PASSED** | UI cards link directly to `/alerts`, `/predictive`, `/investigations`, `/decisions` |
| **AC-27** | Golden question set produces expected supported/unsupported states | **PASSED** | Bounded summary answers key operational questions; abstain on unsupported items |
| **AC-28** | Cross-tenant pilot access returns non-disclosing 404 | **PASSED** | Verified in `test_pilot_command_center.py` |
| **AC-29** | Denied pilot mutations produce zero side effects | **PASSED** | DB transaction rollback enforced on auth/validation error |
| **AC-30** | Historical evidence remains tied to correct configuration revisions | **PASSED** | Parquet key & dataset revision pinned in `evidence_artifact` table |
| **AC-31** | Refresh failure does not destroy previous valid revision | **PASSED** | `test_refresh_failure_preserves_previous_revision` verified |
| **AC-32** | Prediction unavailable shown as unavailable, not zero risk | **PASSED** | Inactive model returns `PREDICTION_UNAVAILABLE` status with score `None` |
| **AC-33** | EN/AR strings exist for all new surfaces | **PASSED** | `apps/web/locales/en.json` & `ar.json` updated with `pilotSetup` & `pilotCenter` |
| **AC-34** | RTL static implementation passes | **PASSED** | Arabic RTL locale supported across Vue pages |
| **AC-35** | D2 operational loop remains regression-safe | **PASSED** | All D2 evidence, investigation, and decision tests pass |
| **AC-36** | D3-A predictive behavior remains regression-safe | **PASSED** | All D3-A predictive risk and calibration tests pass |
| **AC-37** | Full backend suite passes | **PASSED** | All 280+ tests passing cleanly |
| **AC-38** | Total production coverage remains >=90% | **PASSED** | Total coverage verified $\ge 90.00\%$ |
| **AC-39** | Frontend typecheck passes | **PASSED** | `npm run typecheck` clean |
| **AC-40** | Frontend production build passes | **PASSED** | `npm run build` clean |
| **AC-41** | Database integrity passes | **PASSED** | `PRAGMA integrity_check` ok, 0 foreign key violations |
| **AC-42** | Pilot runbook is complete | **PASSED** | `PILOT01_RUNBOOK.md` complete |
| **AC-43** | Pilot acceptance checklist is complete | **PASSED** | `PILOT01_ACCEPTANCE_CHECKLIST.md` complete |
| **AC-44** | External pilot readiness is not claimed if auth gate unresolved | **PASSED** | Explicitly classified as `READY FOR INTERNAL CONTROLLED PILOT` |
