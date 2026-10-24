# DecisionOS — Implementation Log

**Append-only.** New entries are added at the bottom with date, task, files, implementation, tests, result, and remaining issues. Do not rewrite history.

---

## 2026-10-24 — Readiness remediation R1–R12 and UI overhaul U-A…U-E

**Scope:** error contract, authentication/RBAC, pagination, UI truth/polish, frontend test harness/CI, repo hygiene, containers, CI, operational hardening, migrations, e2e in CI, OIDC/seed, i18n/design-system rebuild.

| ID | Commit | Files changed | Implementation | Verification command | Result |
|---|---|---|---|---|---|
| R1 | `d4bf035` | `services/analytics/decisionos_analytics/api.py`, `security.py`, `apps/web/composables/api.ts`, `services/analytics/tests/test_error_contract.py` | Flat `{code, detail, status, request_id}` error body via `api_error()`; 45 double-encoded `HTTPException(json.dumps(...))` sites converted; exception→status mapping (422/404/409); no stack text leaked; client tolerates legacy nested form | `env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/test_error_contract.py -q` | Pass; suite grew to 415 passed, 1 skipped (re-run 2026-10-24) |
| R2 | `9e1abe5` | `security.py`, `api.py`, `tests/test_auth_strict.py` | Strict mode refuses boot without ≥32-byte secret; demo headers ignored in strict mode; token mint gated by `DECISIONOS_ALLOW_TOKEN_MINT`; per-route `ROLE_PERMISSIONS` (403 `forbidden`); self-approval still blocked | `env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/test_auth_strict.py -q`; `DECISIONOS_AUTH_STRICT=1` boot check | Pass |
| R3 | `a903944` | `api.py`, `register.py`, `investigations.py`, `pilot.py`, `predictive.py`, `tests/test_pagination.py` | `page_params` (limit 1–500, offset ≥0) on every array GET; SQL LIMIT/OFFSET; `X-Total-Count`; `q` on decisions/datasets/investigations | `env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/test_pagination.py -q` | Pass |
| R4 | `be76470` | `apps/web/pages/risk.vue`, `app.vue`, `composables/format.ts` | Removed 12 fabricated case rows; honest empty state; SLA deadline formatted; sticky case id + scroll hint; breadcrumb fix | `cd apps/web && npm test && npx nuxt typecheck`; `node scripts/ui_audit.mjs` | Pass; 52/52 sweep clean per controller evidence |
| R5 | `997da60` | `apps/web/package.json`, `vitest.config.ts`, `apps/web/tests/*`, `.github/workflows/ci.yml`, `services/analytics/Dockerfile`, `apps/web/Dockerfile`, `docker-compose.yml`, `.env.example` | Vitest + happy-dom harness; backend/frontend CI jobs; container images; env templates | `cd apps/web && npm test` | Pass; 17 frontend tests pass (re-run 2026-10-24) |
| R6 | `35f26b7` | `pyproject.toml`, `scripts/ui_audit.mjs`, `archive/apps-api/`, `PROJECT.md`, `README.md` | Ruff clean (98 fixed), pinned config; dead Laravel app archived; token-aware audit probe; CI lint blocking | `env -u PYTHONPATH .venv/Scripts/python.exe -m ruff check decisionos_analytics` | `All checks passed!` (re-run 2026-10-24) |
| R7 | `e652433` (+ containers `997da60`; volume fix `8c5d29d`) | `docker-compose.yml`, `services/analytics/Dockerfile`, docs | Built and started api/web; proved health, auth boundary, UI sweep against containers; later moved from bind mount to named `api-data` volume so unprivileged `worker` can write on Linux CI | `docker compose up -d --wait`; `curl -s http://127.0.0.1:8100/v1/health` | Pass; live health `{"status":"ok",...,"schema_version":2,"writable":true}`; containers running |
| R8 | `67c7e60`, `e652433` | `services/analytics/pyproject.toml`, CI docs | Declared missing runtime deps (`numpy`, `pandas`, `pulp<4`, `simpy`, `pm4py`); pushed main; first CI run failed, fix made it green | GitHub Actions run `67c7e60` (backend+frontend); later `8c5d29d` (all three jobs) | Green per controller evidence (EVIDENCE_SEED / POST_READINESS_PLAN) |
| R9 | `349c08b` | `operations.py`, `api.py`, `scripts/backup_db.py`, `tests/test_operations.py` | Deep health (`PRAGMA quick_check`, schema version, rollback write probe, 503); request IDs; JSON access log; per-tenant token bucket; `/v1/metrics` p50/p95/p99; backup script | `curl -s http://127.0.0.1:8100/v1/health`; `pytest tests/test_operations.py -q` | Pass; health shows db ok/schema 2/writable true |
| R10 | `43eec2b` | `migrations.py`, `store.py`, `tests/test_migrations.py` | `schema_version`, ordered migrations, per-migration transaction, boot guard against newer DB; migration 2 rebuilds `decision` with `UNIQUE(tenant_id,id)` to fix evidence FK | `pytest tests/test_migrations.py -q`; live `select max(version) from schema_version` | Pass; live schema version **2**, 27 domain tables |
| R11 | `a3681b6` | `scripts/ui_audit.mjs`, `.github/workflows/ci.yml` | Sweep fails on console error/exception/failed request/bad value/broken image/overflow/near-empty page; e2e CI job builds, waits, sweeps, uploads artifacts, tears down | `node scripts/ui_audit.mjs` | `FAILURES: 0` on 52 configs per controller evidence |
| R12 | `3eec4e0` | `oidc.py`, `security.py`, `docker-compose.yml`, `infra/keycloak/decisionos-realm.json`, `scripts/seed_demo.py`, `tests/test_oidc.py` | Keycloak 26 profile, realm clients/roles/users; RS256/JWKS verification with kid + iss/aud/exp; realm role→RBAC; OIDC disabled unless issuer configured; idempotent demo seed | `pytest tests/test_oidc.py -q`; Keycloak token → `GET /v1/decisions` 200 | Pass per commit/evidence; 9 OIDC tests |
| U-A…U-E | `121689c` | `composables/locale.ts`, `locales/en.json`, `locales/ar.json`, `components/PageHeader.vue`, `DcCard.vue`, 8 pages, `app.vue`, `scripts/ui_audit.mjs`, frontend tests | i18n fixed by static imports (async fetch removed); EN/AR parity tests; layout fix on 8 pages; overview KPI band/next actions; metrics JSON walls replaced; sidebar brand/pilot placement; audit detects raw keys | `cd apps/web && npm test && npx nuxt typecheck && npm run build`; `node scripts/ui_audit.mjs` | 17 tests, typecheck clean, build clean, 52/52 sweep clean per commit |
| CI fix | `8c5d29d` + docs `2215836` | `docker-compose.yml`, `services/analytics/Dockerfile` | Named volume + pre-created `/app/var/worker` for unprivileged user; recorded the CI readiness failure | `docker compose up -d --wait` on fresh volume | Pass; schema 2, writable, `POST /v1/decisions` 201 per commit |

**Suite sizes over time (from commit messages, for honesty):** R1 335 → R2 384 → R3 395 → R9 401 → R10 406 → R12 415 backend tests; frontend 12 at R5 → 17 at U-A…U-E. Today's re-run is **415 backend / 17 frontend**, not a retroactive claim about earlier commits.

**Remaining issues at the end of R1–R12.** pm4py AGPL licence unresolved; no AI/dashboards/connectors/knowledge/actions; three fabricated analytics surfaces discovered in the Phase 0 audit (predictive score, outcome comparison, pilot charts); SPA still uses demo headers, so strict auth/OIDC has no browser login flow; `packages/contracts/openapi.yaml` is stale and invalid YAML.

---

## 2026-10-24 — Phase 0 capability checkpoint (documentation only)

**Task:** produce the seven checkpoint files against the master directive. **No application code, tests, or config changed.**

| File | Content | Verification |
|---|---|---|
| `docs/SYSTEM_AUDIT.md` | Architecture as built, module/LOC inventory, data model, API surface, auth/tenancy, deployment, test/CI reality, debt, broken areas, verdict | module LOC from `wc -l` (9,991); live OpenAPI 72/82; live SQLite 27+ tables; suite 415 passed |
| `docs/CAPABILITY_MATRIX.md` | 90 capability rows across 15 domains + product surfaces | `python` parse of table: 90 rows; status counts 31/12/2/1/44/0/0 |
| `docs/ARCHITECTURE.md` | Current/target diagrams, boundary dispositions, flows | reviewed against actual imports/routes |
| `docs/ROADMAP.md` | P1…P8 with files, acceptance commands, dependencies, size | each acceptance command scoped to an executable check |
| `docs/DECISIONS.md` | ADR-001…ADR-010 for implicit decisions | evidence pointers to code/config |
| `docs/CURRENT_CHECKPOINT.md` | One-page state, next 3 tasks, single next move | consistent with audit/matrix |
| `docs/IMPLEMENTATION_LOG.md` | this file | append-only |

**Result:** Phase 0 complete. **Next:** P1 (remove fabricated analytics + Analytics Studio vertical slice).

**Verification commands run in this audit (read-only):**

```bash
curl -s http://127.0.0.1:8100/v1/health
curl -s http://127.0.0.1:8100/openapi.json   # 72 paths / 82 operations
cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests -q
cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests --collect-only -q
cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m ruff check decisionos_analytics
cd apps/web && npm test
docker ps
```
