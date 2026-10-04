# DecisionOS — D2 Certification Remediation

## 1. Starting Commit
- **Starting Commit**: `596a0845097527dea9f3cd02878f66c3ef765fb0`
- **Feature Branch**: `feature/d2-evidence-investigation-loop`
- **Pre-D2 Baseline Tag**: `decisionos-pre-d2` (`344597a`)
- **Remediation Commit**: `26dac50` (`fix(d2): close independent certification blockers`)

---

## 2. D2-CERT-001 — Parquet Evidence Retrieval
- **Reproduction**: Evidence artifacts with `row_count > 100` are stored as Parquet files in `ObjectStore`. Calling `GET /v1/evidence/{id}` reached `pl.read_parquet(io.BytesIO(...))` in `evidence.py` line 249, which raised `NameError: name 'io' is not defined` because module `io` was used without top-level import.
- **Root cause**: `evidence.py` attempted to construct `io.BytesIO(...)` without `import io`.
- **Fix**: Added top-level `import io` in `decisionos_analytics/evidence.py`.
- **Regression test**: Added `test_parquet_backed_evidence_retrieval_and_integrity` in `services/analytics/tests/test_evidence.py`. The test generates a dataset with 150 rows (> 100 threshold), verifies `storage_format == "parquet"` and `parquet_key` existence in DB, issues `GET /v1/evidence/{id}`, and asserts HTTP 200, row count 150, digest verification, and zero local filesystem path leaks (`"C:" not in body`).
- **Result**: PASSED.

---

## 3. D2-CERT-002 — Decision Lifecycle Enforcement
- **Before**: `register.py` declared `VALID_TRANSITIONS` dictionary, but `transition_status()` bypassed it, allowing arbitrary transitions such as `CLOSED -> DRAFT`, `SUPERSEDED -> DRAFT`, `ACCEPTED -> DRAFT`, `ACTIVE -> PROPOSED`, and `EVALUATED -> ACCEPTED`.
- **After**: Enforced strict state machine guard inside `transition_status()` in `decisionos_analytics/register.py`:
  ```python
  allowed = VALID_TRANSITIONS.get(rec.status, set())
  if new_status not in allowed:
      raise ValueError(f"Invalid status transition from {rec.status.value} to {new_status.value}")
  ```
  And updated `api.py` endpoint `transition_decision_api` to catch invalid transitions and return HTTP 409 Conflict with structured JSON code `invalid_transition`.
- **Valid transition matrix**:
  - `draft` → `proposed`
  - `proposed` → `accepted`, `rejected`, `deferred`, `abandoned`
  - `accepted` → `implementation_pending`, `superseded`
  - `implementation_pending` → `active`, `abandoned`
  - `active` → `review_due`, `superseded`
  - `review_due` → `evaluated`, `superseded`
  - `evaluated` → `closed`, `superseded`
- **Invalid transition tests**:
  Added test matrix in `services/analytics/tests/test_register.py` (`test_decision_lifecycle_enforcement_matrix`) testing invalid transitions:
  - `closed` → `draft` (rejected)
  - `superseded` → `draft` (rejected)
  - `accepted` → `draft` (rejected)
  - `active` → `proposed` (rejected)
  - `evaluated` → `accepted` (rejected)
- **DB unchanged evidence**: Asserted that upon rejected invalid transition attempts, SQLite database status column remains unchanged and no state mutation or orphan record is committed.

---

## 4. D2-CERT-003 — Decision Schema Consolidation
- **Previous schema owners**: Schema ownership was split between `store.py` (`CREATE TABLE decision ... PRIMARY KEY(tenant_id, id)`) and `register.py` (`DECISION_SCHEMA` with `PRIMARY KEY(id)`), while `api.py` executed `DECISION_SCHEMA`, creating initialization-order-dependent schema drift.
- **Final schema owner**: Consolidated schema ownership in `Store` (`store.py`). Updated `register.py` `DECISION_SCHEMA` to match `store.py` with `PRIMARY KEY (tenant_id, id)`. Removed redundant `executescript(DECISION_SCHEMA)` calls in `api.py`.
- **Migration/compatibility**: Safe idempotency via `CREATE TABLE IF NOT EXISTS`.
- **Composite tenant integrity**:
  Parent table `decision` uses composite `PRIMARY KEY (tenant_id, id)`. Child table `decision_evidence_binding` references composite foreign key `FOREIGN KEY (tenant_id, decision_id) REFERENCES decision(tenant_id, id)`.
- **Initialization-order test**: Added `test_decision_schema_initialization_order_determinism` in `tests/test_register.py`. Verifies that whether `Store` initializes first or `DECISION_SCHEMA` executes first, the resulting SQLite table `decision` has exact compound primary key `["tenant_id", "id"]`.

---

## 5. D2-CERT-004 — Coverage
- **Before**: 88%
- **After**: 90% (2508 / 2785 statements, 277 missing, raw 90.05%)
- **Which meaningful tests increased coverage**:
  - `tests/test_d2_remediation_coverage.py`: Added high-value domain regression tests for evidence sampling limit controls (`MAX_UNSAMPLED_ROWS`), investigation idempotency on episode launch (`POST /v1/monitoring/episodes/{id}/investigate`), claim creation with evidence binding, decision freeze enforcement, alert lifecycle state transitions, cross-tenant evidence binding rejection, and malformed request contract handling (HTTP 422/404/409).
  - `tests/test_evidence.py`: Added Parquet evidence retrieval and canonical digest integrity verification.
  - `tests/test_register.py`: Added complete decision lifecycle transition matrix and duplicate binding idempotency tests.

---

## 6. Tamper Fail-Safe Behavior
- **Verification**: Updated `evidence.py` to raise `EvidenceError("integrity_mismatch", ...)` whenever the computed canonical digest of fetched evidence does not match stored `canonical_digest`.
- **API Behavior**: Updated `api.py` to return HTTP 409 Conflict with content `{"code": "integrity_mismatch", "detail": "..."}` rather than returning corrupted payload with 200 OK.
- **Regression test**: Updated `test_e2e_decision_loop.py` tamper assertion (`test_corrupted_evidence_tamper_failsafe`) to verify HTTP 409 Conflict.

---

## 7. Backend Tests
- **Run 1**: 241 passed in 45.62s
- **Run 2**: 241 passed in 46.77s
- **Run 3**: 241 passed in 45.39s
- **Default**: 241 passed in 44.17s

---

## 8. Coverage
```
Name                                     Stmts   Miss  Cover   Missing
----------------------------------------------------------------------
decisionos_analytics\__init__.py             1      0   100%
decisionos_analytics\api.py                752     71    91%   91-96, 149, 165, 184, 238-239, 243, 249, 275, 278-279, 299, 302-305, 329, 335, 353, 387, 429, 431, 440, 459-460, 474-475, 479-480, 517-518, 541-544, 547-548, 565, 589-590, 620-621, 713, 753-754, 790, 815-818, 843-844, 907-908, 939-940, 959-962, 1037-1038, 1104, 1117-1119, 1121, 1150, 1204, 1229
decisionos_analytics\bilingual.py           62      2    97%   94, 126
decisionos_analytics\config.py              14      0   100%
decisionos_analytics\evidence.py           102      0   100%
decisionos_analytics\execution.py           87     13    85%   32, 37-44, 65, 76, 107, 131
decisionos_analytics\forecasting.py        204     33    84%   77, 87, 114, 117, 122-126, 128-131, 139, 144, 149-152, 186-189, 222-223, 277-279, 316, 319, 355, 365, 388, 398
decisionos_analytics\grain.py               37      0   100%
decisionos_analytics\investigations.py     117      0   100%
decisionos_analytics\monitoring.py         273     74    73%   64, 79-80, 86, 88, 144, 183, 329-375, 393-440, 511, 597-632
decisionos_analytics\objectstore.py         50      5    90%   23, 48, 60, 69-70
decisionos_analytics\optimization.py       185      9    95%   265, 279-280, 286-294, 321
decisionos_analytics\parsing.py            108     15    86%   50, 52-54, 79, 93, 96, 103, 110-111, 126-129, 137
decisionos_analytics\pipeline.py            74      9    88%   32, 37-41, 115, 123, 125, 133
decisionos_analytics\register.py           199      2    99%   549-550
decisionos_analytics\scanning.py            51     15    71%   30-32, 48-58, 73
decisionos_analytics\semantics.py           62      0   100%
decisionos_analytics\serve.py                4      4     0%   3-8
decisionos_analytics\simulation.py         216     12    94%   69, 78, 102, 104, 106, 108, 113, 235-236, 293, 325, 372
decisionos_analytics\store.py               31      0   100%
decisionos_analytics\workflow.py           156     13    92%   55, 75, 99-100, 110, 112-115, 127, 129, 134, 150
----------------------------------------------------------------------
TOTAL                                     2785    277    90%
```

---

## 9. Tenant Isolation
- **Suite**: Executed `tests/test_tenant_security.py` and `tests/test_tenant_security_investigations.py`.
- **Results**: Cross-tenant attempts across `investigations`, `claims`, `evidence`, `monitoring`, and `decision_evidence_binding` returned HTTP 404 / 403 / 409 with ZERO state mutation or database side effects.

---

## 10. Database Integrity
- **PRAGMA foreign_keys**: `1`
- **PRAGMA integrity_check**: `ok`
- **Orphan Row Check**:
  - `investigation` → `tenant`: `0`
  - `evidence_artifact` → `investigation`: `0`
  - `investigation_claim` → `investigation`: `0`
  - `investigation_claim` → `evidence`: `0`
  - `decision_evidence_binding` → `decision`: `0`
  - `decision_evidence_binding` → `evidence_artifact`: `0`

---

## 11. Ruff
- **Command**: `.venv\Scripts\python.exe -m ruff check .`
- **Result**: Pre-existing findings only. Zero new lint findings in modified production code.

---

## 12. TypeScript / Build
- **Typecheck**: `npm run typecheck` in `apps/web` → PASSED.
- **Build**: `npm run build` in `apps/web` → PASSED (built in 5.1s).

---

## 13. Git Diff
- **Status**: 8 modified/new files committed in targeted commit `26dac50`.
- **Whitespace check**: `git diff --check` clean.

---

## 14. Remaining Findings
- None for blockers D2-CERT-001 through D2-CERT-004.

---

## 15. Remediation Verdict

READY FOR RE-CERTIFICATION
