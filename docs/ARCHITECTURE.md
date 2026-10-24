# DecisionOS — Architecture (current and target)

**Date:** 2026-10-24 · **Commit:** `121689c` · Phase 0 documentation only

This document separates **what is built** from **what the directive requires**. The target is a modular monolith plus one worker, not a microservice fleet; the directive explicitly warns against Kafka/Spark/Kubernetes unless justified.

---

## 1. Current architecture (as built)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Browser :3000                                                                │
│ Nuxt 3 SPA (ssr:false), 14 route components, EN/AR static JSON bundles       │
│ X-Tenant: tenant_alpha · X-User: alpha.manager (demo actor selector)         │
└───────────────────────────────────┬──────────────────────────────────────────┘
                                    │ HTTP JSON, no bearer token
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ FastAPI :8100 — one process, one file (api.py, 2,394 LOC)                    │
│                                                                              │
│ middleware: CORS · request-id · JSON access log · token bucket · metrics     │
│ auth: HMAC JWT or OIDC bearer; demo headers in dev; per-route RBAC           │
│ errors: flat {code, detail, status, request_id}; validation→422              │
│                                                                              │
│  ┌───────────────┬────────────────┬────────────────┬──────────────────────┐  │
│  │ ingestion     │ analytics      │ prediction     │ decision             │  │
│  │ pipeline.py   │ semantics.py   │ forecasting.py │ register.py          │  │
│  │ parsing.py    │ execution.py   │ predictive.py  │ optimization.py      │  │
│  │ scanning.py   │ monitoring.py  │ risk.py        │ simulation.py        │  │
│  │ grain.py      │ workflow.py    │                │ investigations.py    │  │
│  │               │                │                │ evidence.py          │  │
│  └───────┬───────┴───────┬────────┴───────┬────────┴──────────┬───────────┘  │
│          │               │                │                   │              │
│          ▼               ▼                ▼                   ▼              │
│   SQLite control.sqlite3 (schema v2, 27 tables)                              │
│   Local filesystem object store (quarantine, Parquet revisions, evidence)    │
│                                                                              │
│   outbox_event ── written, never dispatched                                  │
│   alert_delivery ── written, never sent                                      │
│   audit_event ── write-only, no read API                                     │
└──────────────────────────────────────────────────────────────────────────────┘

Callers: scripts/seed_demo.py, scripts/ui_audit.mjs, backend tests.
External identity: optional Keycloak :8081 (profile auth) issuing RS256 tokens.
```

**What this diagram means.** Every engine is a Python module imported by one API file. There is no internal service boundary, no message broker, no worker, no cache, no vector store, no AI client. Uploads, forecasts, process analyses and solver runs execute inside the request. The only persistent contracts are SQLite rows plus Parquet/JSON objects in a local directory. That is adequate for a single-node pilot and inadequate for the target product.

### 1.1 Runtime and dependency inventory

| Layer | Current choice | Constraint it creates |
|---|---|---|
| HTTP | FastAPI + Uvicorn, one process | No independent scaling of heavy analytics |
| Compute | Polars, pandas, NumPy, scikit-learn, statsforecast, PuLP, SimPy, pm4py | Whole-dataset in-memory execution; AGPL from pm4py |
| State | SQLite WAL, single writer | No multi-replica writes; no row-level concurrency |
| Files | Local filesystem object store | Not shared across replicas; no lifecycle policy |
| Frontend | Nuxt 3 SPA, hand-written SVG/canvas charts | No charting/component library for dashboards |
| Identity | HMAC + Keycloak OIDC | No browser login flow |
| Jobs | none | Synchronous work; outbox decorative |
| Observability | stdout JSON + in-process ring | No durable traces/metrics/log aggregation |

---

## 2. Target modular architecture

```
                          ┌──────────────────────────────────────────────┐
                          │ Presentation: Nuxt 3 SPA                     │
                          │ Home · Chat · Data · Analytics · Prediction  │
                          │ Decision · Knowledge · Monitoring · Admin    │
                          └──────────────────────┬───────────────────────┘
                                                 │ OIDC PKCE or scoped token
                                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ API LAYER (FastAPI routers, thin)                                            │
│ authn · tenant context · RBAC · request validation · idempotency · errors    │
│ tracing · pagination · OpenAPI contract generated from code                  │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ INTELLIGENCE ORCHESTRATOR (new)                                              │
│ intent → context → plan → tool selection → execution → validation → output   │
│ tool registry · permissions · cancellation · retry · execution history       │
└───┬───────────┬───────────┬───────────┬───────────┬───────────┬──────────────┘
    │           │           │           │           │           │
    ▼           ▼           ▼           ▼           ▼           ▼
┌────────┐ ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌─────────┐ ┌──────────────┐
│Semantic│ │Analytics│ │Prediction│ │Decision │ │Knowledge│ │Action Engine │
│Layer   │ │Engine   │ │Engine    │ │Engine   │ │Engine   │ │(new)         │
│upgrade │ │upgrade  │ │upgrade   │ │upgrade  │ │new      │ │registry,     │
│metrics │ │query,   │ │train/eval│ │scenario │ │docs,    │ │approval,     │
│dims,   │ │profile, │ │registry, │ │persist, │ │chunks,  │ │execute,      │
│joins   │ │stats    │ │drift     │ │compare, │ │hybrid   │ │retry, audit  │
│        │ │         │ │          │ │recommend│ │search   │ │              │
└───┬────┘ └────┬────┘ └────┬─────┘ └────┬────┘ └────┬────┘ └──────┬───────┘
    │           │           │            │           │             │
    └───────────┴───────────┴─────┬──────┴───────────┴─────────────┘
                                  ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ AI ROUTER (new)                                                              │
│ provider registry · adapters (OpenAI-compatible, Anthropic, Gemini, local)   │
│ model capability/cost/privacy routing · fallback · token/cost ledger         │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ DATA & ARTIFACT FOUNDATION                                                   │
│ dataset registry · connectors · ingestion jobs · quality/lineage             │
│ semantic metrics · evidence/provenance · artifact store (dashboards,         │
│ analyses, reports, predictions, cases) · document index                      │
│ PostgreSQL control plane + Parquet/DuckDB analytics + object storage         │
└──────────────────────────────────────────────────────────────────────────────┘

Cross-cutting: GOVERNANCE (identity, policy, audit, retention, approvals),
OBSERVABILITY (metrics/logs/traces, cost), JOBS (worker, schedules, retries).
```

**Non-negotiable rule carried into the target:** deterministic engines produce numbers; AI interprets, plans, and explains. The LLM never computes a KPI, score, forecast, or optimisation result.

---

## 3. Boundary-by-boundary disposition

| # | Boundary | What exists today | What is missing | Disposition | Proposed location |
|---|---|---|---|---|---|
| 1 | **API layer** | 82 operations in `api.py`; flat error contract; request IDs; auth; RBAC; pagination | Router split; generated OpenAPI; idempotency middleware; versioning policy; audit read API | **Upgrade (refactor)** | `decisionos_analytics/api/routers/*.py`; keep handlers as thin adapters |
| 2 | **Orchestrator** | None; endpoints call engines directly | Intent, planning, tool registry, execution state, cancellation, retry | **New** | `orchestrator/` wrapping existing engines as tools |
| 3 | **Analytics engine** | Polars metric execution for count/ratio/duration; forecasting series builder; process metrics | Ad-hoc dataset query, profiling, statistics (distribution/correlation/regression), segmentation, saved analyses | **Upgrade** | `analytics/query.py`, `analytics/profile.py`, `analytics/stats.py` (wrap `execution.py`) |
| 4 | **Prediction engine** | StatsForecast suite with rolling-origin eval; risk classifiers + calibration code; registry; **fake scoring** | Real training/persist/load; feature contracts enforced; model comparison UI; drift; outcome tracking; explanations | **Upgrade + new training service** | `prediction/train.py`, `prediction/registry.py`, `prediction/scoring.py`, `prediction/drift.py` |
| 5 | **Decision engine** | Decision register, 12-state lifecycle, amendments, outcome review; PuLP solver; SimPy simulation | Scenario persistence/compare/history; recommendation ranking; automated outcome measurement | **Upgrade** | `decision/register.py`, `decision/scenario.py`, `decision/recommend.py` |
| 6 | **Knowledge engine** | None | Document ingest, OCR, chunks, embeddings, hybrid search, citations, access-aware retrieval | **New** | `knowledge/` + document/vector store |
| 7 | **AI router** | None | Provider registry, adapters, model routing, fallback, usage ledger, local models | **New** | `ai/providers/`, `ai/router.py`, `ai/usage.py` |
| 8 | **Semantic layer** | Versioned metric definitions + approval; limited expression types | Entity model, joins, metric owner/targets, richer expressions, certification UI | **Upgrade** | `semantic/` (extend `semantics.py`, `execution.py`) |
| 9 | **Action engine** | None; outbox + alert_delivery tables unused | Action registry, approval, execution, retry, audit, notifications, tasks | **New** | `action/` + worker |
| 10 | **Governance** | HMAC/OIDC, RBAC, tenant isolation, audit writes, rate limit, deep health | Login UI, secrets/KMS, classification/PII, retention, audit read/export, approvals, CVE scan | **Upgrade** | `governance/` (wrap `security.py`, `operations.py`, add policy) |
| 11 | **Artifact system** | Evidence artifacts, decisions, forecasts, datasets | Generic artifact table + type registry + versions + permissions + execution history | **New (thin)** | `artifacts/` table + service; reuse `evidence_artifact` |
| 12 | **Job/worker layer** | None | Durable jobs, retries, progress, cancellation, outbox dispatcher, schedules | **New** | `jobs/` + one worker process |
| 13 | **Observability** | In-process metrics/logs | Durable metrics/logs/traces; provider/model cost; queue depth | **Upgrade** | OpenTelemetry + Prometheus-compatible exporter |

### Disposition summary

- **New modules:** orchestrator, knowledge, AI router, action engine, artifact service, job/worker, recommendation service.
- **Upgrades:** API split, semantic layer, analytics query/profile/stats, prediction training/scoring/drift, decision scenario persistence, governance/admin.
- **Wrappers around existing code (do not rewrite):** `forecasting.py`, `workflow.py`, `monitoring.py`, `optimization.py`, `simulation.py`, `evidence.py`, `parsing.py`, `grain.py`, `migrations.py`. These modules are the strongest part of the codebase and should be preserved behind interfaces.
- **Replace only if justified:** pm4py (AGPL) and the SQLite control plane (single writer), each behind an interface so replacement is a swap, not a rewrite.

---

## 4. Key flows (target)

### 4.1 Analytics flow

```
request(metric|dataset, window, dimensions, filters)
  → API validates tenant + permission
  → Semantic layer resolves definition version + source revision
  → Analytics engine compiles plan (read-only, bounded, whitelisted predicates)
  → Polars/DuckDB/Postgres executes
  → Evidence service stores plan + result + digest + data revision
  → Response includes rows, quality flags, evidence id, limitations
```
Today this exists for certified metrics only. The target adds ad-hoc dataset queries and a chart spec that references the same evidence artifact.

### 4.2 Prediction flow (target)

```
objective → target spec → feature contract → training dataset revision
  → train candidates (baseline first) → rolling-origin evaluation
  → calibration → model artifact + metrics + intended/excluded use
  → approval → active
  → score(entity, as_of) → immutable prediction row
  → outcome join at maturity → accuracy/drift monitoring → retrain or rollback
```
Today only the forecasting half is real. Risk scoring is a constant and must be disabled until this flow exists.

### 4.3 Decision flow

```
trigger (alert/investigation/request)
  → assemble options + constraints + evidence
  → forecast/simulate/optimise each option
  → compare expected outcome vs baseline + uncertainty
  → human review → register decision (brief, counterevidence, evidence bindings)
  → implement → review due → record observed outcome
  → evaluate vs expectation → lesson stored
```
Today steps 1-4 and 6-8 exist in fragments; scenario persistence/comparison and recommendation ranking are missing; the comparison endpoint must not be used.

### 4.4 Dashboard / artifact flow (target)

```
NL request or manual builder
  → orchestrator drafts a dashboard spec (JSON, validated against schema)
  → each component resolves to a metric/dataset query
  → queries execute with evidence capture
  → renderer draws charts from data, never from hard-coded SVG
  → save artifact (owner, version, permissions, evidence, refresh policy)
  → edit through chat = produce a new validated spec version
```
No part of this flow exists today (no dashboard schema, table, route, or chart library).

### 4.5 AI flow (target)

```
chat request → orchestrator context (tenant/workspace/dataset/conversation)
  → intent classification → plan
  → tool calls (semantic query, dataset query, forecast, process, decision, knowledge)
  → each tool enforces its own permissions and returns structured evidence
  → LLM explains/plans only; never invents numbers
  → response with tool results + evidence/citations
  → conversation persisted; usage/cost recorded
```

### 4.6 Security flow

```
request → OIDC/JWT verification → tenant + user + role
  → route permission → tool permission → data scope filter
  → if action: approval requirement → execute with audit
  → every mutation writes audit_event and (for analysis) evidence
```

---

## 5. Deployment target

Keep it small and defensible:

| Concern | Current | Target |
|---|---|---|
| API | 1 container, SQLite | 1-2 API containers, PostgreSQL control plane |
| Analytics | in-process Polars | in-process Polars/DuckDB over Parquet; read-only DB connectors |
| Worker | none | 1 worker container for ingestion/training/reports/outbox/actions |
| Frontend | Nuxt SPA | same Nuxt SPA + login + workspace shell |
| Identity | Keycloak profile | Keycloak (or external OIDC) in all non-demo deployments |
| Files | local volume | S3-compatible object store (MinIO on-prem) |
| Vector | none | pgvector or a local index; no separate vector service initially |
| Observability | stdout | OpenTelemetry + Prometheus/Grafana or hosted equivalent |
| Jobs | none | DB-backed job table + worker; no Kafka/Celery requirement |

**Explicit non-goals for the next phase:** Kubernetes, Spark, multi-region, event streaming, separate microservices per engine. None is justified by current volume or team size.

---

## 6. Architectural risks to resolve before scaling

1. **Trust boundary:** fabricated scoring/comparison/charts must be removed before any AI or dashboard work; otherwise the new layers will faithfully explain invented numbers.
2. **pm4py AGPL:** decide licence vs replacement before commercial hosting. Wrap it behind `ProcessEngine` now so replacement is contained.
3. **SQLite:** migrate control-plane metadata to PostgreSQL before multi-user or multi-replica deployment; keep Parquet for analytical payloads.
4. **Heavy synchronous requests:** move uploads, training, process mining and reports to the worker with job status/progress.
5. **OpenAPI drift:** generate the contract from FastAPI and delete/repair `packages/contracts/openapi.yaml` (currently invalid YAML at line 243).
6. **Dual evidence stores:** converge on `evidence_artifact`; retire `store.save_evidence` or make it a view/adapter.
7. **No login:** the SPA cannot use the secure backend. This is a product blocker, not a polish item.
