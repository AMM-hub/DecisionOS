# DecisionOS — System Audit

**Date:** 2026-10-24 · **Commit:** `121689c` · **Phase:** 0 (audit only; no application code changed)

**Method.** Read the master directive and evidence seed; inspected every Python module, the migration DDL, the FastAPI route table, the Nuxt page tree, CI/compose/Dockerfiles; ran read-only checks: live `GET /v1/health`, live OpenAPI extraction, `pytest --collect-only`, the full backend suite, the frontend suite, and `ruff check`. Claims marked VERIFIED below are tied to a command I ran or to a controller-verified CI run. Everything else is explicitly qualified.

---

## 0. Verdict (read this first)

**This is a well-tested, narrow decision-intelligence pilot for support-ticket operations — not a universal enterprise intelligence platform.**

What is real: CSV → quarantine → bounded parse → grain proof → immutable dataset revisions → versioned/approved metric definitions → Polars metric execution → evidence with canonical digests → forecasting with honest refusals → process mining → PuLP optimisation → SimPy simulation → anomaly rules/episodes → decision register with outcome review. The backend test suite is real (415 passed) and the auth/tenant boundary is real in strict mode.

What is not real: the AI layer (none), the chat workspace (none), dashboards (none), document/knowledge search (none), data connectors beyond CSV (none), customer/financial/strategic domains (none), action engine (none). More seriously, **three user-visible surfaces fabricate analytics**:

1. `POST /v1/predictive/score` returns a constant `score = 0.65` for every eligible case (`api.py:1812`). No model is loaded or executed.
2. `GET /v1/decisions/{id}/outcome-comparison` returns hard-coded baseline/observed values (`18.5`, `11.2`, `4.2%`, `19.5h`, `14.2h`) and a hard-coded verdict (`api.py:2360-2388`).
3. The Pilot Command Center renders hand-authored SVG "12-week telemetry" and "SLA decay" charts with fixed values `94.2%`, `92.0%`, `T+38h` (`apps/web/pages/pilot/index.vue:110-222`).

These are not demo fixtures behind a flag; they are returned/displayed as live results. They violate the directive's Rule 3 and Rule 4 and are P0.

---

## 1. Identity and runtime (verified)

| Item | Actual |
|---|---|
| Product name | DecisionOS (FastAPI title: “DecisionOS local control plane (demo stand-in)”, `api.py:144`) |
| Backend | Python package `decisionos_analytics`, FastAPI, 28 modules, **9,991 LOC** |
| Python | Docker `python:3.13-slim` (`services/analytics/Dockerfile`); local venv 3.14; CI 3.12; `pyproject.toml` requires `>=3.12` |
| Frontend | Nuxt 3 + Vue 3 SPA (`ssr: false`), TypeScript strict, **14 page components**, 2 components, 3 composables |
| Storage | One SQLite file, schema version **2**; live DB has **27 application tables + `schema_version`** (28 including `sqlite_sequence`) |
| Deployment | `docker compose`: `api` :8100, `web` :3000, `keycloak` :8081 under profile `auth` |
| API | Live OpenAPI: **72 paths / 82 operations** |
| Tests | **415 passed, 1 skipped** (re-run 2026-10-24); 47 backend test files; 17 frontend tests in 4 spec files |
| CI | 3 jobs (backend, frontend, e2e); controller-verified run `121689c` green |

Commands that produced the numbers:

```bash
curl -s http://127.0.0.1:8100/v1/health
# {"status":"ok",...,"checks":{"db":"ok","schema_version":2,"writable":true}}

curl -s http://127.0.0.1:8100/openapi.json | python -c "import json,sys;d=json.load(sys.stdin);print(len(d['paths']),sum(len([m for m in v if m in ('get','post','put','patch','delete')]) for v in d['paths'].values()))"
# 72 82

cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests -q
# 415 passed, 1 skipped in 77.41s

cd apps/web && npm test
# Test Files 4 passed (4) / Tests 17 passed (17)

cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m ruff check decisionos_analytics
# All checks passed!
```

Note: the evidence seed says “31 tables”; the live DB (both `var/worker` and the container volume) has 27 domain tables plus `schema_version`. The seed number is stale. Verified by querying both SQLite files.

---

## 2. Architecture as built

```
                       ┌──────────────────────────────────────┐
 Browser ──:3000──────►│ Nuxt 3 SPA (ssr:false, 14 routes)    │
                       │ demo identity headers X-Tenant/X-User│
                       └───────────────┬──────────────────────┘
                                       │ fetch JSON, no bearer token
                                       ▼
                       ┌──────────────────────────────────────┐
                       │ FastAPI api.py (2,394 LOC)           │
                       │  72 paths / 82 operations            │
                       │  flat error contract, request ids,   │
                       │  in-process rate limit + metrics     │
                       └───┬───────┬───────┬───────┬──────────┘
                           │       │       │       │
        ┌──────────────────┘       │       │       └──────────────────┐
        ▼                          ▼       ▼                          ▼
┌───────────────┐   ┌──────────────────┐  ┌─────────────────┐  ┌──────────────┐
│ ingestion     │   │ analytics        │  │ decision        │  │ governance   │
│ parsing.py    │   │ semantics.py     │  │ register.py     │  │ security.py  │
│ scanning.py   │   │ execution.py     │  │ optimization.py │  │ oidc.py      │
│ grain.py      │   │ forecasting.py   │  │ simulation.py   │  │ operations.py│
│ pipeline.py   │   │ workflow.py      │  │ evidence.py     │  │ migrations.py│
└───────┬───────┘   │ monitoring.py    │  │ investigations.py│  └──────┬───────┘
        │           │ risk.py          │  │ pilot.py         │         │
        │           └────────┬─────────┘  └────────┬─────────┘         │
        ▼                    ▼                     ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ SQLite control.sqlite3 (schema v2, 27 tables)  +  local filesystem objects  │
│ Parquet dataset revisions, evidence payloads, upload quarantine             │
└─────────────────────────────────────────────────────────────────────────────┘
```

There is **no service boundary inside the backend**: `api.py` imports and orchestrates every engine directly. There is no worker, queue, scheduler, cache, object-store service, vector store, or AI provider client. `outbox_event` rows are written but never dispatched. `alert_delivery` has no producer and no sender.

---

## 3. Backend module inventory (9,991 LOC)

| Module | LOC | Responsibility |
|---|---:|---|
| `api.py` | 2,394 | FastAPI app, 82 operations, auth middleware, error contract, orchestration |
| `forecasting.py` | 751 | StatsForecast suitability, rolling-origin evaluation, baseline-first selection, intervals, persistence |
| `monitoring.py` | 628 | DataHealth, seasonal-MAD/residual/CUSUM detectors, alert rules, episodes, lifecycle |
| `register.py` | 608 | Decision register, 12-state lifecycle, amendments, counterevidence, outcome records |
| `migrations.py` | 578 | Ordered SQLite DDL migrations, schema-version guard, FK rebuild |
| `risk.py` | 534 | Target suitability, case-state logic, base-rate/logistic/RF classifiers, Platt calibration, metrics |
| `simulation.py` | 458 | SimPy discrete-event queue simulation, time-varying arrivals, priority/FIFO |
| `pilot.py` | 440 | Pilot contract, data-readiness gate, workflow mapping, config merge |
| `optimization.py` | 438 | PuLP/CBC capacity allocation LP/MIP, slack, IIS infeasibility report |
| `predictive.py` | 438 | Predictive target/model registry, model lifecycle transitions, prediction persistence |
| `workflow.py` | 367 | PM4Py event log, bottlenecks, variants, conformance, case SLA, throughput |
| `investigations.py` | 345 | Investigation CRUD, structured claims, episode→investigation launch |
| `operations.py` | 290 | Deep health, request IDs, JSON logs, token bucket, metrics, p50/p95/p99 |
| `security.py` | 264 | HMAC JWT, strict-auth boot guard, RBAC matrix, identity resolution |
| `evidence.py` | 256 | Metric evidence capture, canonical digest, JSON/Parquet storage, tamper check |
| `bilingual.py` | 195 | Arabic normalisation, bilingual labels/search matching |
| `parsing.py` | 149 | Encoding/dialect detection, bounded CSV parse, type inference, rejected rows |
| `pipeline.py` | 148 | Upload→scan→parse→revision pipeline, atomic publish, lease sweep |
| `execution.py` | 146 | Predicate compilation, Polars execution for count/ratio/duration percentile |
| `oidc.py` | 121 | RS256/JWKS verification, kid lookup, iss/aud/exp |
| `store.py` | 117 | Thread-local SQLite connections, audit/outbox/evidence helpers |
| `semantics.py` | 88 | Pydantic metric-definition and query contracts |
| `scanning.py` | 73 | Format sniffing, xlsx bomb/macro guard, formula-injection screen |
| `objectstore.py` | 70 | Local filesystem object store |
| `grain.py` | 66 | Grain candidate proof over full data; relationship profile helper |
| `config.py` | 20 | Upload/parse limits |
| `serve.py` | 8 | Uvicorn factory entrypoint |
| `__init__.py` | 1 | Package marker |

---

## 4. Frontend inventory (verified by file tree)

14 route components, all client-rendered:

| Route | LOC | Real backend wiring |
|---|---:|---|
| `/` | 173 | datasets, metrics, uploads, outbox, decisions, episodes |
| `/uploads` | 197 | upload init/content/finalize, preview, grain |
| `/datasets` | 120 | list, grain confirmation, publish |
| `/metrics` | 437 | definitions propose/approve/withdraw, metric query |
| `/forecasts` | 320 | suitability, evaluate, train, predict; custom canvas chart |
| `/workflow` | 329 | bottleneck/variant/conformance/case/throughput |
| `/scenarios` | 184 | templates, solver run |
| `/monitoring` | 402 | health, rules, evaluate, episodes |
| `/investigations` | 203 | create/list |
| `/investigations/[id]` | 424 | detail, claims, evidence capture |
| `/decisions` | 744 | create/list/transition/outcome/evidence |
| `/risk` | 337 | **no queue load**; action calls use a duplicated `/v1` prefix |
| `/pilot` | 336 | pilot summary (real counts) + **static SVG charts** |
| `/pilot/setup` | 198 | bootstrap/config calls |

Shared: `components/PageHeader.vue` (39), `components/DcCard.vue` (20), `composables/api.ts` (116), `composables/format.ts` (63), `composables/locale.ts` (58), `shared/types.ts`. Total frontend source+tests ≈ 4,917 LOC.

No charting library is installed (`apps/web/package.json` has only `nuxt` and `vue`). Charts are hand-written SVG/canvas.

---

## 5. Data model (verified live, 27 domain tables)

| Purpose | Tables | Notes |
|---|---|---|
| Identity / tenancy | `tenant`, `workspace`, `member` | demo tenants seeded; member table unused by auth |
| Ingestion | `upload`, `dataset`, `dataset_revision` | revision manifest JSON holds object keys/schema/row counts |
| Semantic layer | `definition`, `definition_version`, `definition_publication` | immutable versions + effective intervals |
| Evidence / provenance | `evidence_artifact`, `evidence`, `investigation`, `investigation_claim`, `decision_evidence_binding` | **two parallel evidence systems**: `evidence` (generic JSON) and `evidence_artifact` (governed, digest-checked) |
| Decisions | `decision` | brief/counterevidence/amendments/outcome stored as JSON |
| Monitoring | `alert_rule`, `condition_state`, `alert_episode`, `alert_delivery` | delivery table never consumed by a sender |
| Forecasting | `forecast_model` | JSON model spec; series embedded in spec |
| Predictive | `predictive_target`, `predictive_model`, `predictive_prediction` | registry + lifecycle + immutable predictions |
| Pilot | `pilot` | config JSON for mapping/SLA/rules/risk |
| Operational | `outbox_event`, `audit_event`, `schema_version` | outbox has no dispatcher; audit has no read API |

Absent: dashboards, dashboard versions, artifacts (generic), conversations/messages, AI providers/models/prompts, documents/chunks/embeddings, connectors/schedules, actions/approvals, targets/objectives, model drift/monitoring, data classification/PII, data lineage.

---

## 6. API surface (live OpenAPI, 72 paths / 82 operations)

| Domain | Ops | What is exposed |
|---|---:|---|
| health / metrics | 2 | deep health, in-process counters |
| auth | 2 | token mint (gated), verify |
| uploads | 6 | init, put bytes, finalize, list, preview, grain candidates |
| datasets | 5 | list, schema, grain candidates, confirm grain, publish revision |
| metrics | 6 | ops metrics, definitions list/create/approve/withdraw, query |
| forecasts | 4 | suitability, train, predict, evaluate |
| workflow | 5 | bottlenecks, variants, conformance, case metrics, throughput |
| jobs | 1 | outbox read |
| scenarios | 2 | templates, solve |
| decisions | 8 | create/list/get/transition/outcome/evidence bind/evidence list/outcome comparison |
| simulations | 1 | run DES |
| monitoring | 10 | health (all/per dataset), rules CRUD, evaluate, conditions, episodes, episode status |
| bilingual | 2 | labels, search |
| evidence | 2 | capture, get |
| investigations | 6 | create/list/get/status/claims create/claims list |
| predictive | 8 | targets list/create, models list/register/transition, score, prediction get, prediction evidence |
| pilots | 13 | semantic pack, create/list/get/status, validate, refresh, summary, bootstrap, mapping, SLA, rules, risk target |

Contract drift: `packages/contracts/openapi.yaml` is an M1-era skeleton (server `/api/v1`, cookies/CSRF) and is **not valid YAML** at line 243 (`description: half-open [start,end)` as a flow mapping); it is not the live 82-operation contract. The live `/openapi.json` is the only usable contract.

---

## 7. Capability summary

The full 90-row map is in `docs/CAPABILITY_MATRIX.md`. Counts: **31 VERIFIED COMPLETE, 12 PARTIALLY IMPLEMENTED, 2 IMPLEMENTED — UNVERIFIED, 1 EXISTS — NEEDS UPGRADE, 44 MISSING, 0 BLOCKED, 0 NOT APPLICABLE.**

The implemented spine is genuinely strong for one operational domain. Everything in the directive's AI, dashboard, knowledge/research, customer, financial, strategic, action, and adaptive-modeling domains is absent.

---

## 8. Auth and tenancy (as built)

- **Default (demo) mode:** identity is `X-Tenant` + `X-User`; only `tenant_alpha`, `tenant_beta` and three demo users are accepted. The SPA always sends `tenant_alpha` and an actor selector (`api.ts:34`).
- **Strict mode:** `DECISIONOS_AUTH_STRICT=1` refuses to boot without a ≥32-byte `DECISIONOS_JWT_SECRET`; only `Authorization: Bearer` is accepted; demo headers are ignored (`security.py:27-35`, `security.py:237-250`).
- **Tokens:** HMAC-SHA256 local tokens (`security.py:132`), and OIDC RS256/JWKS when `DECISIONOS_OIDC_ISSUER` is set (`oidc.py:76`, `security.py:226-231`). Token minting is off unless `DECISIONOS_ALLOW_TOKEN_MINT=1`.
- **RBAC:** `ops_manager`, `semantic_modeler`, `qa_operator`, `viewer`; route handlers request permissions via `ctx(..., permission=...)` (`security.py:112-120`). Self-approval is blocked.
- **Tenant isolation:** composite `(tenant_id, id)` keys; cross-tenant lookups return 404. Covered by tenant-security tests.
- **Frontend auth:** **MISSING.** No login page, no token storage, no refresh/logout, no user admin. In strict mode the SPA cannot authenticate at all. The actor selector is not authorization; it is a demo affordance.

---

## 9. Deployment and operations

| Area | Reality |
|---|---|
| Compose | `api`, `web`, optional `keycloak`; named volume `api-data`; no TLS/reverse proxy |
| Container state | verified running: `decisionos-api-1`, `decisionos-web-1`, `decisionos-keycloak-1` |
| CI | backend (ruff + pytest + coverage gate 85), frontend (typecheck + vitest + build), e2e (compose build/up, 52-config Chrome sweep, artifacts) |
| Health | deep `PRAGMA quick_check` + schema version + rollback write probe; 503 on failure (`operations.py:150`) |
| Observability | one JSON access log per request, request IDs, in-process latency ring, `/v1/metrics` counters; **no external metrics/log/trace backend** |
| Rate limit | in-process per-tenant token bucket (120/min default); single node only (`operations.py:201`) |
| Queue/worker | none; uploads are processed synchronously in the request; outbox rows never dispatched |
| Backup | `scripts/backup_db.py` (`VACUUM INTO` + integrity check + sha256) — manual, not scheduled |
| Scaling | SQLite single writer; WAL enabled; all analysis loads whole Parquet into memory; no pagination of engine results beyond metric `limit` |
| Secrets | env vars; `.env.example`; SQLite and uploaded objects unencrypted at rest |
| Licensing | **pm4py AGPL v3** is a runtime dependency for `/v1/workflow/*` (`workflow.py:90`, `pyproject.toml:23`); commercial hosting requires a licence or replacement |

Stale infrastructure: `infra/docker-compose.yml` still describes the archived Laravel API plus Postgres/Redis/MinIO and is not what is deployed. `README.md` still claims 173 tests and a Laravel production authority. `archive/apps-api/` is a dead Laravel skeleton.

---

## 10. Tests and CI: what is actually proven

- Backend: 415 passed, 1 skipped (re-run). Suite covers error contract, strict auth, pagination, operations, migrations, OIDC, tenant isolation, ingestion E2E, forecasting, workflow, monitoring, optimisation, simulation, decision/evidence loop, pilot journeys.
- Frontend: 17 tests passed (api error mapping, formatting, locale, page smoke).
- Coverage: controller reports **90.05%**; I did not re-run coverage in this audit, so treat that number as EVIDENCE_SEED, not fresh.
- Browser sweep: 52 configs (13 routes × 2 viewports × 2 locales), controller/CI reports `FAILURES: 0`; I did not re-run it.
- CI run `121689c` is green per the evidence seed; `git log` shows the commit. I did not query GitHub (no `gh`).
- Not covered: fabricated predictive score, fabricated outcome comparison, static pilot charts, risk page queue, xlsx parsing, frontend auth, connectors, AI, dashboards. Passing tests currently *lock in* the fabricated score (`test_risk_api.py:133` only asserts `score is not None`).

---

## 11. Technical debt and fragility (ranked)

| # | Debt | Evidence | Impact |
|---|---|---|---|
| 1 | Fabricated predictive score | `api.py:1812` (`score = 0.65`) | Every risk number is a lie; decisions/evidence built on it are unsound |
| 2 | Fabricated outcome comparison | `api.py:2360-2388` | “Supported improvement” is hard-coded, not measured |
| 3 | Fabricated pilot charts | `pilot/index.vue:110-222` | Executive UI presents static SVG as telemetry |
| 4 | Risk workspace never loads | `risk.vue:257` (`riskQueue.value = []`); no list-predictions API | `/risk` is permanently empty; drawer actions unreachable |
| 5 | Double API prefix in risk actions | `risk.vue:273,284` (`/v1/...` against `/v1` base) | Calls resolve to `/v1/v1/...` and 404 |
| 6 | XLSX accepted but not parsed | `config.py:14`, `scanning.py:29`, `pipeline.py:41` (`parse_csv` always) | `.xlsx` upload passes scan then fails/garbles as CSV |
| 7 | Evidence records wrong definition version | `evidence.py:174` (literal `1`) | Provenance is wrong for any metric at v2+ |
| 8 | Two evidence stores | `store.save_evidence` + `evidence_artifact` | Ambiguous source of truth; retention/lineage unclear |
| 9 | 2,394-line API monolith | `api.py` | Every change touches one file; no module boundaries; test surface coupled |
| 10 | No worker/queue; sync heavy work | `pipeline.py:24`, `api.py` | Uploads/forecasts/solver block requests; no retry/cancel |
| 11 | Outbox never dispatched | `outbox_event`, `GET /v1/jobs/outbox` only | No downstream automation; “jobs” are decorative |
| 12 | Alert delivery never sent | `alert_delivery` table; no producer/sender | Alerts stop at the UI |
| 13 | Ad-hoc DDL inside a request handler | `api.py:1341-1378` re-creates monitoring tables on every `/monitoring/evaluate` | Two schema authorities (migrations + handler); drift risk |
| 14 | Strict auth unusable from SPA | `api.ts:34`; no login | Production auth backend cannot serve the product |
| 15 | Invalid/stale API contract | `packages/contracts/openapi.yaml:243` | Cannot generate clients; contract and code diverge |
| 16 | pm4py AGPL | `pyproject.toml:23` | Commercial distribution risk |
| 17 | SQLite single-writer + local FS objects | `store.py`, `objectstore.py` | No horizontal scale; backup/restore manual |
| 18 | In-process metrics/rate limit | `operations.py` | Per-process only; meaningless with >1 replica |
| 19 | Docs drift | `README.md:7,206` | 173 tests / Laravel authority / Postgres claims are false today |
| 20 | Hand-written charts only | `package.json`, `forecasts.vue:101` | No reusable visualization layer for dashboards |
| 21 | No dependency/vulnerability scan | `.github/workflows/ci.yml` | Supply-chain exposure untracked |

---

## 12. Security findings

**Working:** strict-mode boot refusal, HS256 forgery/expiry rejection, OIDC RS256 kid/iss/aud/exp validation, per-route RBAC, self-approval block, tenant-scoped 404s, flat error bodies (no stack traces), formula-injection screen on CSV, xlsx bomb/macro guard, rate limiting, request IDs, audit writes.

**Gaps:** no frontend login/SSO; no secrets manager or KMS (JWT secret in env, API keys would follow the same pattern); no encryption at rest for SQLite/Parquet; no PII detection/classification/masking; no data retention/deletion controls; audit log is write-only (no read API, no export); no action approval model because there are no actions; no prompt-injection/tool-permission layer because there is no AI; no dependency/CVE scan; Keycloak dev defaults (`admin` / `decisionos-admin`) are committed in compose/env.

---

## 13. What this is / what this is not

**This is:** a credible, unusually well-tested **operational decision-intelligence pilot** for a support-ticket domain. It can ingest a CSV, prove a grain, publish immutable revisions, define and approve metrics, compute them reproducibly with evidence, forecast, mine a process, solve a capacity allocation, simulate a queue, detect anomalies, register a decision, bind evidence, and review an outcome. The evidence/provenance design is the best part of the system. The auth/tenant boundary is real when strict mode and OIDC are enabled.

**This is not:** the platform described in the directive. There is no AI provider layer, no chat/orchestrator, no dashboard builder, no analytics studio with SQL/EDA, no knowledge/vector search, no case-study or competitor research, no customer/financial/strategic domains, no action engine, no model training/drift/retraining, no generic artifact registry, no industry packs. And the predictive/outcome/pilot surfaces currently show invented numbers, so the platform is **less trustworthy than its test count suggests**.

**Bottom line for the owner:** the foundation is worth preserving, but the product cannot be called an intelligence platform until (a) fabricated analytics are removed, (b) a real query/chart/artifact surface exists, and (c) an AI layer is added on top of grounded tools. The recommended first move is in `docs/ROADMAP.md` P1; the full map is `docs/CAPABILITY_MATRIX.md`.
