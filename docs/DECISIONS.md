# DecisionOS — Architecture Decision Records

**Format:** ADR-001…ADR-0NN. Status is one of Accepted / Superseded / Proposed / Open. Each record states context, decision, alternatives rejected, consequences, and code evidence. New ADRs append; do not rewrite accepted history.

---

## ADR-001 — SQLite control plane with Polars/Parquet analytics

**Status:** Accepted for the single-node pilot; **revisit before multi-user production** (see ADR-002).

**Context.** The pilot needs durable tenants, datasets, metric definitions, evidence, decisions and predictions on one machine, with no DBA. Analytical payloads are columnar and read-mostly; the control plane is small and transactional.

**Decision.** Keep one SQLite database (`control.sqlite3`, WAL, foreign keys, versioned migrations) for control-plane metadata, and store dataset revisions/evidence as Parquet/JSON in a local object store. Execute metrics with Polars over the Parquet revision. This is explicitly a local/pilot authority, not the production metadata system of record (`store.py:1-8`).

**Alternatives rejected.** (a) PostgreSQL from day one — operational overhead before product fit; (b) DuckDB as the control plane — weaker multi-writer/transaction story for metadata; (c) an ORM — the explicit SQL/composite-key pattern is easier to audit here.

**Consequences.** Fast local development, trivial backup (`VACUUM INTO`), strong test isolation. Costs: single writer, no horizontal scale, no row-level security, whole-file encryption absent, and a future migration of 27 tables to PostgreSQL. The migration must preserve composite `(tenant_id, id)` keys and the migration-version guard (`migrations.py:525-578`).

**Evidence.** `store.py:32`, `migrations.py:18-19,405-430,530`, `pipeline.py:76-78`, live `PRAGMA` checks.

---

## ADR-002 — One FastAPI service, not microservices

**Status:** Accepted; extend with a worker before splitting services.

**Context.** All engines are Python and share the same data structures (Polars frames, Pydantic contracts, SQLite store). Traffic is pilot-scale. The directive warns against Kafka/Spark/Kubernetes unless justified.

**Decision.** Keep a modular monolith: one FastAPI process exposes all domains; engines are modules; the API file orchestrates them. Add a single worker process for long-running jobs rather than decomposing into services.

**Alternatives rejected.** (a) One service per engine (analytics/prediction/decision/knowledge) — network contracts, deployment overhead, distributed transactions with no current need; (b) serverless functions — cold starts and local file/SQLite coupling; (c) a separate BI service — duplicates the semantic layer.

**Consequences.** Simple deployment and debugging; one test suite; one process to secure. Costs: `api.py` is 2,394 LOC and couples every domain; heavy work blocks requests; independent scaling is impossible. The planned remedy is a router split plus a worker, not microservices.

**Evidence.** `api.py:125-2394`; single Uvicorn entrypoint `serve.py`; compose has one `api` service.

---

## ADR-003 — Nuxt 3 SPA with statically imported i18n bundles

**Status:** Accepted.

**Context.** The product is an authenticated internal console with heavy client interaction (tables, forms, charts). Arabic/English with RTL is required. Server-side rendering adds no SEO value for an internal SPA and complicates auth.

**Decision.** Nuxt 3 + Vue 3 with `ssr: false`, TypeScript strict, static `en.json`/`ar.json` imports in `composables/locale.ts`, and a synchronous `t()` function. A prior async fetch-based i18n implementation rendered raw keys in production and was replaced (U-A…U-E, `121689c`).

**Alternatives rejected.** (a) Next.js/React — no reason to migrate a working Vue app (directive: keep the current framework unless inadequate); (b) SSR — auth and deployment complexity with no benefit; (c) runtime i18n fetch — caused the production-key regression.

**Consequences.** Fast static build, simple RTL switching, testable locale bundles. Costs: no SSR/SEO, no route-level code splitting strategy yet, hand-written charts because no chart library is installed, and a thin frontend test suite (17 tests) relative to the backend.

**Evidence.** `apps/web/nuxt.config.ts:4`, `composables/locale.ts:2-7,45`, `locales/en.json`, `locales/ar.json`, commit `121689c`.

---

## ADR-004 — Dual authentication: HMAC JWT plus OIDC (Keycloak)

**Status:** Accepted for backend; **frontend half is unimplemented** (ADR-010).

**Context.** Local development and automated tests need a self-contained token path. Real deployments need an external identity provider, SSO, and key rotation. Both must coexist without letting a token choose its own verification path.

**Decision.** In dev, accept whitelisted demo headers. In strict mode, require a bearer token: verify HS256 with a ≥32-byte shared secret, or RS256 against a configured OIDC issuer's cached JWKS. OIDC is attempted only when `DECISIONOS_OIDC_ISSUER` is set; otherwise the server cannot be opted into OIDC by a token. Map realm roles to the same RBAC matrix.

**Alternatives rejected.** (a) Local HMAC only — no SSO/key rotation for real deployments; (b) OIDC only — tests and local demos need a running IdP; (c) trusting `X-Tenant`/`X-User` in strict mode — spoofable.

**Consequences.** Strong, testable backend boundary; two token formats to maintain; strict mode refuses to boot with weak secrets. Critical gap: the SPA has no login/callback/refresh and always sends demo headers (`api.ts:34`), so the secure backend cannot serve the browser product yet.

**Evidence.** `security.py:27-35,112-120,132-264`, `oidc.py:76-121`, `infra/keycloak/decisionos-realm.json`, `tests/test_auth_strict.py`, `tests/test_oidc.py`.

---

## ADR-005 — Named Docker volume instead of a bind mount for API data

**Status:** Accepted.

**Context.** The API image runs as the unprivileged `worker` user. On a Linux CI runner a bind-mounted host directory is owned by the runner UID, so the container cannot create `/app/var/worker`; readiness then fails. Docker Desktop on Windows masked this for weeks.

**Decision.** Use the named volume `api-data` for `/app/var` and pre-create `/app/var/worker` owned by `worker` in the image. Document a local `./var:/app/var` override for developers who want to inspect the SQLite file.

**Alternatives rejected.** (a) Run the container as root — unacceptable; (b) chown the host directory in CI — brittle and runner-specific; (c) keep the bind mount and relax permissions — hides the defect.

**Consequences.** Reliable CI and clean container boots; data lives in a Docker volume (harder to inspect without an override); backup must run inside the container or against the volume.

**Evidence.** `docker-compose.yml:6-12`, `services/analytics/Dockerfile`, commits `8c5d29d`, `2215836`.

---

## ADR-006 — pm4py AGPL v3: accepted for the pilot, unresolved for commercial hosting

**Status:** **Open / blocked on business decision.**

**Context.** `/v1/workflow/*` uses pm4py for the event-log object model and variant extraction (`workflow.py:90`). pm4py Community Edition is AGPL v3. Network use of AGPL code triggers source-disclosure obligations for the combined service unless a commercial licence is purchased.

**Decision.** Accept pm4py for the internal pilot and keep all PM4Py usage behind `workflow.py` so it can be replaced. Do not claim commercial readiness until one of the options below is chosen.

**Alternatives rejected for now.** (a) Ignore the licence — unacceptable legal risk; (b) immediate rewrite — delays P1–P5 with no product value today; (c) a different mining library (e.g. permissive DFG implementation) — simplest long-term option, but needs a focused port and golden tests.

**Options and consequences.**
1. **Buy a pm4py commercial licence** — fastest, recurring cost, no code change.
2. **Replace with an internal implementation** — DFG/variant/conformance/throughput over Polars is a few hundred lines; the existing tests (`test_workflow.py`) become the acceptance contract; removes AGPL from the runtime.
3. **Isolate as a separate AGPL service** — still legally delicate for a hosted product; not recommended.

**Evidence.** `pyproject.toml:23`, `workflow.py:1-27,90`, `docs/POST_READINESS_PLAN.md` (P9 risk).

---

## ADR-007 — Refusal and evidence over fabricated results

**Status:** Accepted in design; **violated in three places today** (must be enforced).

**Context.** The directive forbids fake analytics, random predictions, hard-coded dashboard results, and fake confidence. The existing code already models refusal as a first-class outcome for forecasting and workflow (“insufficient_data” with next actions), and captures evidence with canonical digests for metric queries.

**Decision.** Deterministic engines must either produce a traceable result or refuse with a machine-readable reason. Every analytical answer should carry evidence (plan, dataset revision, metric version, digest, quality flags). AI may explain but never compute numbers.

**Alternatives rejected.** (a) Best-effort guesses to keep the UI populated; (b) demo fixtures that look like live data; (c) confidence scores without calibration.

**Consequences.** Honest UX, harder demos, more explicit empty states. The current violations are: constant predictive score (`api.py:1812`), hard-coded outcome comparison (`api.py:2346-2388`), and static pilot charts (`pilot/index.vue:110-222`). P1 must remove them; tests must assert refusal, not merely non-null values.

**Evidence.** `forecasting.py:63-75,651-653`, `workflow.py:40-45`, `evidence.py:97-199`, `test_e2e_flow.py` refusal assertions.

---

## ADR-008 — Versioned metric definitions with approval and effective intervals

**Status:** Accepted.

**Context.** Business metrics change meaning over time. Overwriting a definition makes historical evidence unreproducible. Similar metric names must not be assumed identical.

**Decision.** A metric has a stable identity, immutable content versions, and publications with `effective_from`/`effective_to`. Queries resolve the active publication and pin its version into evidence. Propose/approve/withdraw are separate actions; self-approval is refused; approval requires a role permission.

**Alternatives rejected.** (a) Mutable metric rows — breaks reproducibility; (b) free-text SQL definitions — unsafe and unauditable; (c) a single global semantic release — coarse and hard to roll back per metric.

**Consequences.** Reproducible answers and a real governance story; more tables and ceremony; only three expression types today. A defect remains: `evidence.py:174` writes literal `definition_version=1`, so evidence for v2+ is mislabelled; P1 must fix it.

**Evidence.** `semantics.py:55-88`, `migrations.py:89-120`, `api.py:561-655`, `evidence.py:141-199`.

---

## ADR-009 — Support-ticket operations is the first (and only) industry pack

**Status:** Accepted for the pilot; to be generalised in P3/P8.

**Context.** The directive requires industry-extensible packs, but building banking/retail/healthcare packs before the core data/knowledge/AI layers exist would produce shallow demos. The pilot already has a coherent domain: support tickets, SLA breach, queue capacity.

**Decision.** Ship one deep pack (`support_ticket_operations`) with real semantics, monitoring, workflow mapping, risk target and decision loop. Treat it as the reference implementation of a pack, not as the universal model.

**Alternatives rejected.** (a) Many shallow packs — violates “complete capability, not superficial feature”; (b) hard-code support-ticket fields into the core — blocks other industries; (c) no pack at all — loses the only working end-to-end story.

**Consequences.** Credible pilot, clear template for future packs, but every future industry starts with extraction work. P3 must move dataset/entity/metric definitions into configurable pack metadata; P8 ships the second pack.

**Evidence.** `pilot.py:42-126`, `api.py:1937-2345`, `apps/web/pages/pilot/*`, `fixtures/support-tickets/`.

---

## ADR-010 — Demo identity in the SPA, strict identity at the API

**Status:** Accepted **only for the pilot**; **must be superseded before any production deployment.**

**Context.** The SPA needs to demonstrate separation of duties (modeler proposes, manager approves) without building a login flow. The API already has a strict token path.

**Decision.** For the pilot, the SPA sends `X-Tenant: tenant_alpha` plus a demo actor (`alpha.manager` / `alpha.modeler`) and exposes an actor selector. The API treats this as dev-only; strict mode ignores the headers and requires a bearer token.

**Alternatives rejected.** (a) Block the SPA until OIDC login exists — stops all UI work; (b) store a long-lived token in `localStorage` — insecure and still no login; (c) disable strict mode in deployment — unacceptable.

**Consequences.** Fast demo, real backend RBAC tests, and an explicit, visible “internal evaluation only” posture. The cost is that the shipped product cannot authenticate against its own secure backend; the actor selector could be mistaken for authorization. Superseded by P2 (OIDC PKCE login, refresh, logout, role-aware UI).

**Evidence.** `apps/web/composables/api.ts:30-36`, `api.py:72-79,318-347`, `security.py:201-264`, `PROJECT.md` runtime security section.
