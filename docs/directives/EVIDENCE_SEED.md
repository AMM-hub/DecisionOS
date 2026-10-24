# Measured evidence (verified by the controller, 2026-10-24)

Use this as the baseline for Phase 0. Re-verify anything you state; do not contradict it without showing the command.

## Runtime
- Backend: FastAPI on :8100, Python 3.13 in Docker / 3.14 locally, package `decisionos_analytics`, 28 modules, **9,991 lines**.
- Frontend: Nuxt 3 + Vue 3 SPA (`ssr: false`), 15 pages, 2 components (PageHeader, DcCard), :3000.
- Storage: single SQLite control plane, schema **version 2** via `migrations.py` (31 tables).
- Deployment: `docker compose` (api, web, keycloak under profile `auth`), GitHub Actions CI (backend, frontend, e2e).
- Auth: HMAC JWT + Keycloak OIDC (RS256/JWKS), per-route RBAC, tenant isolation by claim/header; **frontend still authenticates with demo X-Tenant/X-User headers — no login screen.**

## API surface
- **72 paths / 82 operations** (OpenAPI at :8100/openapi.json). Pagination (`limit/offset`, `X-Total-Count`, `q`) on list endpoints.
- Domains actually implemented: uploads+quarantine, datasets+grain+publish+revisions, semantic metric definitions (propose/approve/withdraw), metric query execution (Polars), forecasting (statsforecast), predictive models/targets/scoring, workflow/process mining (pm4py), scenarios/optimization (PuLP), monitoring rules/episodes/conditions, investigations+claims, evidence capture, decision register (state machine, outcomes, evidence binding), pilot bootstrap/summary, bilingual labels/search, jobs outbox.

## Verification (all green today)
- 415 backend tests passing, 1 skipped, coverage **90.05%**; ruff **0** findings.
- 17 frontend vitest tests; typecheck 0; build 1.75 MB (420 kB gzip).
- 52-config browser sweep (13 routes × 2 viewports × 2 locales) → **FAILURES: 0**.
- CI run `121689c`: backend ✓ frontend ✓ e2e ✓ (e2e builds images, boots the stack, runs the sweep).

## Absent capabilities (grep-verified: no code, no dependency)
- **No AI layer at all**: no provider adapters, no model router, no chat, no tools/agents, no prompt management, no token/cost tracking. No `openai`/`anthropic`/`google-genai` dependency.
- **No conversational workspace**: zero chat UI/routes.
- **No dashboard builder**: no dashboard spec, no persistence, no chart config, no charting library in `apps/web`.
- **No knowledge engine**: no document ingestion, OCR, embeddings, vector/hybrid search, citations.
- **No data connectors**: only CSV upload. No Postgres/MySQL/MSSQL/REST ingestion.
- **No case-study or competitor research** workspaces.
- **No action engine**: no action registry, approvals, workflow execution, notifications.
- **No industry packs**, no capability registry, no artifact system beyond the decision register.
- **No model registry UI**, no drift detection, no retraining workflow (predictive API exists but is API-only).
- **No pagination UI**, thin frontend tests (4 spec files), no accessibility pass, no dependency-vulnerability scan.

## Licensing risk
- `pm4py` is **AGPL v3** — commercial hosting requires a licence or replacement.

## Known operational limits
- Rate limiting and metrics are in-process (single node); SQLite is single-writer; no queue/worker service.
