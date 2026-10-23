# Project: DecisionOS PILOT-01 Operational QA Verification

## Architecture
DecisionOS is a decision intelligence platform comprising:
1. **Analytics Service (FastAPI + Polars + SQLite)**:
   - Python 3.14 runtime in `services/analytics/.venv/Scripts/python.exe`.
   - Server entrypoint: `decisionos_analytics.serve:app` on port 8100.
   - SQLite control-plane storage with isolated sandboxing via `DECISIONOS_DATA_DIR`.
   - Polars-driven dataset ingestion, grain candidate discovery, and metric calculation.
   - Process mining engine (`pm4py`), predictive risk engine (`scikit-learn`), PuLP optimization solver.
2. **Web Application (Nuxt 3 SPA + Vue 3)**:
   - Node 24 runtime in `apps/web`. Runs on port 3000 (`npm run dev`).
   - Client-side fetch targeting `http://localhost:8100/v1` with tenant headers.
   - Multi-route interface: Executive Pilot Command Center (`/pilot`), Decisions Register (`/decisions`), Investigations Console (`/investigations`).
   - Localization engine with English (`en`) and Arabic (`ar`) RTL layout.
3. **QA & Verification Harnesses**:
   - Isolated SQLite test sandbox (`var/sandbox_pilot01`).
   - Chrome DevTools Protocol (CDP) / Headless Chrome automation (`C:\Program Files\Google\Chrome\Application\chrome.exe`).
   - Multi-threaded Python concurrency harness targeting mutation & queue endpoints.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Service Boot & Health | Boot FastAPI analytics backend and Nuxt web application; verify health endpoints | M1 | ORIGINAL_REQUEST §R1 |
| 2 | Empty-State Navigation | Verify `/pilot`, `/decisions`, `/investigations` render HTTP 200 with zero console errors on clean DB | M1 | ORIGINAL_REQUEST §R1 |
| 3 | Tenant Auth Enforcement | Verify tenant authentication boundary (`X-Tenant`, `X-User`) and isolation guards | M1 | ORIGINAL_REQUEST §R1, §Context |
| 4 | Synthetic Ticket Batch Ingestion | Ingest 50 synthetic support tickets via API; update dataset revision & Pilot KPIs | M1 | ORIGINAL_REQUEST §R1 |
| 5 | Command Center State Refresh | Verify Executive Pilot Command Center reflects new dataset metrics without server restarts | M1 | ORIGINAL_REQUEST §R1 |
| 6 | Browser Matrix Verification | Verify Command Center and Decisions on 1920×1080 and 1366×768 desktop viewports | M2 | ORIGINAL_REQUEST §R2 |
| 7 | RTL & Arabic Localization | Validate Arabic locale toggles `dir="rtl"` with mirrored component layout | M2 | ORIGINAL_REQUEST §R2 |
| 8 | LTR Retention for Numbers & IDs | Validate numbers, percentages, and ticket IDs preserve LTR readability in RTL mode | M2 | ORIGINAL_REQUEST §R2 |
| 9 | Layout & Button Fold Integrity | Validate table headers align correctly, zero element clipping, critical buttons above the fold | M2 | ORIGINAL_REQUEST §R2 |
| 10 | Multi-Thread Concurrent Write Test | Execute 50 concurrent requests against decision mutation and queue evaluation endpoints | M3 | ORIGINAL_REQUEST §R3 |
| 11 | SQLite Lock & Contention Telemetry | Monitor and log `SQLITE_BUSY`, database lock contention, transaction aborts, and memory stability | M3 | ORIGINAL_REQUEST §R3 |
| 12 | Relational Integrity Verification | Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check` on sandbox SQLite database post-stress | M3 | ORIGINAL_REQUEST §R3 |
| 13 | Empirical QA Evaluation Report | Compile comprehensive `PILOT01_EMPIRICAL_QA_REPORT.md` with latencies, logs, DOM snapshots & bottlenecks | M4 | ORIGINAL_REQUEST §R4 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Phase 1: Smoke & Ingestion | Boot services in sandbox, verify empty states on `/pilot`, `/decisions`, `/investigations`, ingest 50 synthetic tickets, verify KPI refresh | None | DONE |
| 2 | Phase 2: Visual & Localization | Headless browser sweep across EN/AR locales and 1920×1080 / 1366×768 viewports; verify RTL, LTR retention, and buttons above fold | M1 | DONE |
| 3 | Phase 3: Stress & Concurrency Gate | 50-thread concurrent write stress test against decision & queue endpoints; lock telemetry, memory monitoring, PRAGMA integrity | M1 | DONE |
| 4 | Phase 4: Verification Report & Artifacts | Compile empirical report `PILOT01_EMPIRICAL_QA_REPORT.md` with latency percentiles, DOM snapshots, logs, and bottlenecks | M1, M2, M3 | DONE |

## Milestone 1 Verified Outputs
- Services: FastAPI backend (port 8100) and Nuxt 3 web app (port 3000) active and healthy in sandbox `var/sandbox_pilot01`.
- Baseline DB: `var/worker/control.sqlite3` 100% untouched and clean at commit `9492676`.
- Empty-State Verification: `scripts/verify_empty_states_cdp.mjs` completed with exit code 0; HTTP 200, 0 unhandled exceptions, 0 console errors. Artifacts in `var/qa_artifacts/empty_state_results.json`, `dom_pilot_empty.html`, `dom_decisions_empty.html`, `dom_investigations_empty.html`.
- Auth Boundary: HTTP 401 on synthetic testing headers (`test-tenant`/`qa-operator`), HTTP 404 on cross-tenant requests.
- Synthetic Ingestion: 50 tickets / 138 rows in `var/qa_artifacts/synthetic_50_tickets.csv`, `status: PASS` readiness gate, dynamic KPI updates (`open_alerts` +1, `high_risk_cases` +1, `open_decisions` +1) verified without restart.
- Gate Reviewers/Challengers/Auditor: 2 APPROVE, 2 APPROVE, 1 CLEAN. Gate PASS.

## Milestone 2 Verified Outputs
- Test Runner: `scripts/verify_phase2_visual_matrix_cdp.mjs` executed and passed 12/12 matrix configurations.
- Matrix Grid: 2 Viewports (1920×1080, 1366×768) × 2 Locales (English LTR, Arabic RTL) × 3 Routes (`/pilot`, `/decisions`, `/investigations`).
- Assertions Verified:
  - Document direction: `dir="rtl"` and `.shell.rtl` active for Arabic; `dir="ltr"` for English.
  - Zero horizontal overflow: `scrollWidth <= clientWidth` on all 12 configurations.
  - Critical action buttons above the fold: all primary action buttons (`Guided Pilot Setup`, `+ Create Decision Brief`, `+ Launch Investigation`) verified at Y <= 160px (margin to fold >= 608px on 768px height).
  - BiDi & LTR retention: Character coordinate range analysis verified physical LTR ordering for numbers, percentages (`50%`), and ticket IDs within RTL text.
  - Zero badge overlap: Pairwise Axis-Aligned Bounding Box (AABB) intersection check detected 0 collisions.
  - Table header alignment: `th` elements align `text-align: right` in Arabic and `left` in English.
- Artifacts: 12 PNG screenshots in `var/qa_artifacts/screenshots/`, 12 DOM snapshots, aggregate JSON telemetry in `var/qa_artifacts/visual_matrix_results.json`.

## Milestone 3 Verified Outputs
- Test Runner: `scripts/run_phase3_concurrency_stress.py` executed cleanly to completion with exit code 0.
- Traffic Composition: 50 concurrent requests release-synchronized via `threading.Barrier(50)` across 5 endpoint categories (`decisions_create`, `decisions_transition`, `monitoring_evaluate`, `predictive_score`, `scenarios_solve`).
- Status Code Distribution: 31x 200 OK, 8x 201 Created, 10x 401 Unauthorized (synthetic tenant boundary), 1x 409 Conflict (duplicate transition collision), 0x 500 (Zero server errors).
- Latency Percentiles (ms): min=312.86, avg=1216.67, p50=1285.49, p95=1504.68, p99=1526.09, max=1530.54. Completed in 1.556s wall clock time.
- SQLite Lock Contention: Zero `SQLITE_BUSY`, `database is locked`, or `OperationalError` observed.
- Process Stability & Memory: WorkingSetSize (RSS) stable at 4.062 MB with zero process crashes (`process_crashed: false`).
- Relational Database Integrity: `PRAGMA foreign_key_check` reported 0 violations, `PRAGMA integrity_check` reported `ok` on sandbox database `var/sandbox_concurrency/control.sqlite3`.
- Baseline DB Preservation: Cryptographic digest of `var/worker/control.sqlite3` verified identical to accepted baseline commit `9492676` (`b0aa71c5f6431b8d1ca530eeaf1f9f0b9aeb5b765977be0345ba40f5a985598e`), 0 git modifications.
- Gate Reviewers/Challengers/Auditor: 2 APPROVE (`reviewer_m3_1`, `reviewer_m3_2`), 2 APPROVE (`challenger_m3_1`, `challenger_m3_2`), 1 CLEAN (`auditor_m3_1`). Gate PASS.
- Artifacts: Telemetry in `var/qa_artifacts/concurrency_stress_results.json` (32,022 bytes).

## Milestone 4 Verified Outputs
- Publication-Grade Report: `PILOT01_EMPIRICAL_QA_REPORT.md` compiled at repository root, covering all 7 mandatory verification sections.
- Verified Scorecard: Phases 1, 2, and 3 certified 100% PASS with empirical evidence across all operational requirements.
- Architectural Bottlenecks & Hardening Recommendations: Detailed analysis of SQLite single-writer lock contention vs WAL mode, object store revision immutability collision handling, Nuxt 3 locale bundling and in-memory caching, and Windows pipe buffer drainer architecture.
- Traceability Matrix: 100% of acceptance criteria from `ORIGINAL_REQUEST.md` (§AC1–§AC8) mapped to concrete empirical evidence and verification artifacts.
- Artifact Catalog: Complete catalog of 34 QA artifacts (totaling 973,812 bytes) with file paths, sizes, descriptions, and SHA-256 prefixes.
- Project Closure: Milestone 1 DONE, Milestone 2 DONE, Milestone 3 DONE, Milestone 4 DONE. PILOT-01 operational QA verification successfully completed and signed off.

## Interface Contracts
### Client ↔ Analytics Backend
- Base URL: `http://localhost:8100/v1`
- Authentication Headers:
  - Whitelisted Demo Headers: `X-Tenant: tenant_alpha`, `X-User: alpha.manager`
  - Synthetic Testing Header Boundary: `X-Tenant: test-tenant`, `X-User: qa-operator` (returns HTTP 401 by tenant guard design)

### Runtime Sandboxing
- Variable: `DECISIONOS_DATA_DIR`
- Sandbox Path: `c:\Users\AMD\Desktop\DecisionOS\var\sandbox_pilot01`
- Baseline DB: `c:\Users\AMD\Desktop\DecisionOS\var\worker\control.sqlite3` (baseline `9492676`, preserved intact)

## Runtime Security
- **Strict auth is opt-in:** `DECISIONOS_AUTH_STRICT=1` requires `DECISIONOS_JWT_SECRET` to be set and at least 32 bytes. If it is missing or too short, the service **refuses to boot** with `RuntimeError: DECISIONOS_AUTH_STRICT=1 requires DECISIONOS_JWT_SECRET to be configured with at least 32 bytes.`
- **JWT-only identity in strict mode:** `Authorization: Bearer <jwt>` is the only accepted identity source. `X-Tenant` / `X-User` demo headers are ignored, not merely unverified, and forged/expired tokens return `401`.
- **Token minting is disabled by default:** `POST /v1/auth/token` returns `404` unless `DECISIONOS_ALLOW_TOKEN_MINT=1`. Keep it off in production; mint tokens out-of-band with the shared secret.
- **RBAC is enforced per route:** mutating routes are mapped to permissions (`write`, `approve`, `transition`, `manage_pilot`, ...) and a role lacking one receives `403` with `code: "forbidden"`.
- **Environment:** `DECISIONOS_AUTH_STRICT`, `DECISIONOS_JWT_SECRET`, `DECISIONOS_ALLOW_TOKEN_MINT`, `DECISIONOS_DATA_DIR` (see `.env.example`).

## List Endpoints
Every `GET` list endpoint accepts bounded pagination:
- `limit` — integer, `1..500`, default `50`.
- `offset` — integer, `>= 0`, default `0`.
- Out-of-range values are rejected with `422` and `code: "invalid_pagination"`.

Responses keep their existing shape (bare array or object with the items key) and add an `X-Total-Count` response header with the unpaginated total for the tenant.

Substring filters (`q`, case-insensitive) are available on:
- `/v1/decisions` — decision title
- `/v1/investigations` — investigation title
- `/v1/datasets` — dataset name

Covered list paths include uploads, datasets, metric definitions, outbox, scenarios/templates, decisions and decision evidence, monitoring health/rules/conditions/episodes, investigations and claims, predictive targets/models, and pilots.
