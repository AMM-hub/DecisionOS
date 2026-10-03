# DecisionOS — Next Phase Plan Forensic Audit & Review

This review records the forensic comparison between the initial `NEXT_PHASE_PLAN.md` draft, the actual DecisionOS repository, and the authoritative `DecisionOS_Master_Business_and_Technical_Specification.md`.

---

## A. FACTUAL CORRECTIONS

Below is the exhaustive list of incorrect or hallucinated statements found in the initial plan, along with their empirical corrections:

1. **Incorrect Claim**: `auth.py` handles Bearer token authentication and tenant verification.
   - **Correction**: `auth.py` **does not exist** in the repository. Authentication is implemented in `api.py` via `ctx(x_tenant, x_user)` checking custom headers (`X-Tenant`/`X-Tenant-ID` and `X-User`).
2. **Incorrect Claim**: `execution.py` owns Decision Brief creation and decision lifecycle state transitions.
   - **Correction**: `execution.py` handles metric plan compilation (`compile_plan`) and typed metric query execution (`execute`) over Polars. Decision Briefs, the Decision Register, and status transitions are owned by `register.py` and served via `@app.*/v1/decisions` in `api.py`.
3. **Incorrect Claim**: Decision status machine is simplified to `DRAFT → APPROVED`.
   - **Correction**: `register.py` ALREADY implements the full 12-state decision lifecycle specified in Spec §19.2 (`draft`, `proposed`, `accepted`, `implementation_pending`, `active`, `review_due`, `evaluated`, `closed`, `rejected`, `deferred`, `abandoned`, `superseded`).
4. **Incorrect Claim**: Forecasting uses `prophet`.
   - **Correction**: `forecasting.py` uses `statsforecast` (`AutoARIMA`, `AutoETS`, `AutoTheta`). `prophet` is not in `pyproject.toml`.
5. **Incorrect Claim**: Proposed next-phase API endpoints use `/api/v1/...` namespace.
   - **Correction**: All existing endpoints in `api.py` strictly use the `/v1/...` prefix convention (e.g., `/v1/decisions`, `/v1/monitoring`).
6. **Incorrect Claim**: Evidence immutability should be enforced via OS file permissions (e.g. `chmod 0444`).
   - **Correction**: OS file permission flags are non-portable on Windows and easily overridden. Logical immutability is enforced at the storage/API boundary via append-only versioning, SHA-256 canonical digests, and the absence of `UPDATE`/`PUT` endpoints for snapshot content.
7. **Incorrect Claim**: Delivery stage D0 is "COMPLETE" because synthetic schemas exist.
   - **Correction**: According to Spec §30.2, D0 requires an authorized source, a named buyer/owner, and a pilot scope. For DecisionOS, D0 is **PARTIAL** (Complete for synthetic demo scope only).
8. **Incorrect Claim**: E2E testing relies on "Playwright E2E PASS".
   - **Correction**: Playwright is not installed in `apps/web/package.json`. Frontend verification relies on `vue-tsc --noEmit` and `npm run build`; E2E API integration testing uses `httpx.AsyncClient` / FastAPI `TestClient`.

---

## B. TRUE ACCEPTED BASELINE

- **Git HEAD Commit**: `ef31e1bbbb4d1d22790f788a1c3ab0c23614ac8c`
- **Branch**: `main`
- **Working Tree Status**: **UNCOMMITTED CHANGES PRESENT**
- **Explanation**: The Round 2 remediation work (closing malformed request handling, solver classification, security input matrix, tenant security regression tests) exists in the working directory as modified/untracked files. It was executed on top of `ef31e1b` but never committed via `git commit`.

---

## C. CORRECTED CURRENT ARCHITECTURE

All modules in `services/analytics/decisionos_analytics/` have been mapped to their exact file responsibilities and verified lines of code in Section 2 of `NEXT_PHASE_PLAN.md`.

---

## D. CORRECTED DELIVERY STAGE ASSESSMENT

Evaluated strictly against Spec §30.2:
- **D0**: PARTIAL (Synthetic demo complete; no live buyer)
- **D1**: PARTIAL (Uploads/DuckDB/Polars/Bilingual working; definition editor UI & evidence missing)
- **D2**: PARTIAL (Monitoring & workflow alerts working; Investigation workspace & evidence snapshots missing)
- **D3**: PARTIAL (Forecasting working; risk classification & survival missing)
- **D4**: PARTIAL (PuLP solver & Decision register working; simulation & causal studies stubbed)
- **D5**: NOT STARTED

---

## E. CORRECTED NEXT PHASE

**Recommended Phase**: **"Evidence, Investigation & Decision Loop" (Phase D2 Completion)**
- Validated Prerequisites: W04 (Auth/Tenancy), W05 (Storage/Revisions), W07 (Datasets), W08 (Definitions), W09 (Typed Queries), W14 (Workflow), W15 (Monitoring) are all sufficiently present to build W10 (Findings/Claims/Evidence) and connect to W16 (Decisions).

---

## F. FINAL DATA MODEL

Four normalized SQLite tables added to `Store`:
1. `investigation` (Primary Key `id`, tenant FK `tenant_id`, `question`, `status`, `owner`, `analytical_state_json`)
2. `evidence_artifact` (Primary Key `id`, tenant FK `tenant_id`, investigation FK `investigation_id`, `resolved_plan_json`, `canonical_digest`, `exactness_class`, `storage_format`, `payload_json`, `parquet_key`)
3. `investigation_claim` (Primary Key `id`, tenant FK `tenant_id`, investigation FK `investigation_id`, evidence FK `evidence_id`, `structured_fact_json`)
4. `decision_evidence_binding` (Primary Key `id`, tenant FK `tenant_id`, decision FK `decision_id`, evidence FK `evidence_id`, `role`)

---

## G. FINAL API CONTRACT

All endpoints strictly use `/v1/`:
- `POST /v1/investigations`
- `GET /v1/investigations`
- `GET /v1/investigations/{id}`
- `POST /v1/investigations/{id}/claims`
- `GET /v1/investigations/{id}/claims`
- `POST /v1/monitoring/episodes/{id}/investigate`
- `POST /v1/evidence`
- `GET /v1/evidence/{id}`
- `POST /v1/decisions/{id}/evidence`

---

## H. FINAL AUTHORIZATION MODEL

Header-based auth (`X-Tenant` / `X-Tenant-ID` and `X-User`) via `ctx(x_tenant, x_user)` in `api.py`. Cross-tenant requests return non-disclosing `404 Not Found`.

---

## I. FINAL ACCEPTANCE CRITERIA

AC-01 through AC-16 (covering idempotent launch, non-disclosing 404s, structured claim facts, pinned dataset/metric revisions, SHA-256 canonical digest validation, evidence sampling caps, 12-state decision lifecycle, bilingual RTL, and tenant security matrix tests).

---

## J. FINAL ORDERED WORK PACKAGES

- **WP-00**: Repository Baseline Freeze & Database Schema Migration
- **WP-01**: Evidence Snapshot Engine (`backend`)
- **WP-02**: Investigation Workspace Core (`backend & API`)
- **WP-03**: Decision Brief Evidence Binding (`backend & API`)
- **WP-04**: Investigation & Decision Register UI (`frontend`)
- **WP-05**: E2E Integration & Tenant Security Regression Suite (`testing`)

---

## K. IMPLEMENTATION READINESS

```text
BASELINE NOT FROZEN
```
