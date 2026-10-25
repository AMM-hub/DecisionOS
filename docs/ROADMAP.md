# DecisionOS — Roadmap P1…P8

**Date:** 2026-10-24 · **Basis:** `docs/SYSTEM_AUDIT.md`, `docs/CAPABILITY_MATRIX.md` (90 rows) · **Commit:** `121689c`

**Ordering rule:** value-to-risk, with correctness before capability. Every phase must leave the previous phase's commands green. Sizes: **S** ≤ 1 week, **M** 1–3 weeks, **L** 3–8 weeks for one focused engineer.

**Current state:** Phase 0 complete. 31 capabilities verified, 44 missing, 3 public surfaces show invented numbers. P1 exists because those three surfaces undermine everything built on top of them.

| Phase | Theme | Size | Blocks | Unlocks |
|---|---|---|---|---|
| P1 | Truth + Analytics Studio vertical slice | M | — | Everyday self-serve use; foundation for dashboards and AI tools |
| P2 | Authenticated AI workspace | L | P1 (query tool) | Conversational intelligence, provider independence |
| P3 | Data foundation 2.0 (connectors/jobs/quality) | L | P1 (artifact/query contracts) | Real company data, scheduled refresh |
| P4 | Dashboard builder + artifact system | L | P1, P2 | Saved dashboards, AI dashboard generation |
| P5 | Prediction engine 2.0 (train/evaluate/monitor) | L | P3 (data), P1 | Real risk scores, churn/demand templates |
| P6 | Knowledge and research | L | P2 (chat), P3 (docs) | Case studies, competitor intelligence, citations |
| P7 | Action + adaptive intelligence | L | P5, P6 | Approved actions, outcome feedback, drift response |
| P8 | Enterprise hardening + industry packs | L | All | Hostable commercial product |

---

## P1 — Truth + Analytics Studio vertical slice  *(smallest change that makes the platform materially more useful)*

**Objective.** Remove every invented number from the product and give analysts the first real self-serve surface: query a published dataset, see a correct table/chart, save the analysis as an evidence-backed artifact.

**Capabilities delivered.** DATA-12 (extended expressions), BI-01/02 (ad-hoc query), SURF-03 (Analytics Studio MVP), SURF-07 (saved analysis artifact), PRED-07 (truthful refusal instead of fake score), DEC-09 (remove fake comparison), OPS-01 (data-fed charts), ADAPT-01 (truthful outcome display).

**Files/modules.**
- Change: `services/analytics/decisionos_analytics/api.py` (split query routes into `api/routers/analytics.py` if the split is cheap; otherwise add handlers), `execution.py` (sum/avg/min/max/count_distinct + time buckets), `evidence.py` (record true definition version), `artifact` model.
- Create: `decisionos_analytics/analytics/query.py` (read-only dataset query over a published revision), `decisionos_analytics/artifacts.py` + `artifact` table migration (id, type, owner, tenant, config, version, evidence_id, created/updated), `apps/web/pages/analytics.vue`, `apps/web/components/Chart.vue` (use a small chart library — e.g. ECharts — or a single reusable SVG renderer).
- Delete/replace: `api.py:1812` constant; `api.py:2346-2388` hard-coded comparison; `pilot/index.vue:110-222` static SVG; `risk.vue:257` empty queue + `risk.vue:273,284` double `/v1` prefix.

**Acceptance commands.**

```bash
# 1. No fabricated analytics remain
grep -R "score = 0.65" services/analytics/decisionos_analytics && exit 1 || true
grep -R "18.5\|94.2%\|T+38h" services/analytics/decisionos_analytics apps/web/pages/pilot && exit 1 || true

# 2. Real query endpoint exists and computes a known aggregate
curl -s -X POST http://127.0.0.1:8100/v1/datasets/$DS/query \
  -H 'X-Tenant: tenant_alpha' -H 'X-User: alpha.manager' -H 'Content-Type: application/json' \
  -d '{"dimensions":["status"],"measures":[{"column":"*","agg":"count","alias":"n"}],"limit":100}' \
  | python -c "import json,sys;d=json.load(sys.stdin);assert d['rows'],d;print(d['evidence_ref'])"

# 3. Backend + frontend suites
cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests -q
cd apps/web && npm test && npx nuxt typecheck

# 4. Saved artifact round-trips
curl -s http://127.0.0.1:8100/v1/artifacts -H 'X-Tenant: tenant_alpha' -H 'X-User: alpha.manager' \
  | python -c "import json,sys;a=json.load(sys.stdin);assert any(x['type']=='analysis' for x in a)"
```

**Dependencies.** None. **Risk:** low. **Estimate:** M (query endpoint 3–4 days, chart + page 3–4 days, artifact table + tests 2 days, removal/truth work 1 day).

**Why this is P1.** It is the smallest change that turns the product from a fixed demo into something an analyst can use on their own data today, and it removes the trust defects that would otherwise poison every later AI/dashboard feature. It also creates the two primitives the AI (P2) and dashboards (P4) need: a bounded query tool and a saved artifact.

---

## P2 — Authenticated AI workspace (provider layer + chat + orchestration)

**Objective.** Add a provider-independent AI layer and a real conversational workspace that can call the deterministic engines — never compute numbers itself.

**Capabilities delivered.** AI-01…AI-04, AI-07, AI-08, SURF-01, GOV-04 (SPA login), GOV-02 (admin roles), AI-05/AI-06 (prompt/usage foundations).

**Files/modules.**
- Create: `ai/providers/{base,openai_compatible,anthropic,gemini,local}.py`, `ai/router.py`, `ai/usage.py`, `ai/prompts.py`, `orchestrator/{planner,tools,executor}.py`, `conversations` + `messages` + `ai_provider` + `ai_model` + `ai_usage` tables, `api/routers/ai.py`, `api/routers/chat.py`, `apps/web/pages/chat.vue`, `apps/web/pages/settings/ai.vue`.
- Tools registered from existing engines: `metric_query`, `dataset_query` (from P1), `forecast`, `workflow_analysis`, `solve_scenario`, `simulate`, `evidence_get`, `decision_create` (draft only).
- Change: `api.py` auth middleware to accept OIDC sessions from the SPA; Keycloak client config in `infra/keycloak/decisionos-realm.json`; `apps/web/composables/api.ts` to send bearer tokens and handle 401/refresh; `security.py` tool-permission checks.

**Acceptance commands.**

```bash
# Provider CRUD never returns the secret
curl -s -X POST http://127.0.0.1:8100/v1/ai/providers -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"local","kind":"openai_compatible","base_url":"http://localhost:11434/v1","api_key":"test"}' \
  | python -c "import json,sys;d=json.load(sys.stdin);assert 'api_key' not in json.dumps(d);print(d['id'])"

# Chat executes a grounded tool and returns an evidence reference
curl -s -X POST http://127.0.0.1:8100/v1/chat -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"message":"What is the open-ticket count this month?","dataset_id":"'$DS'"}' \
  | python -c "import json,sys;d=json.load(sys.stdin);assert d['tool_calls'] and d['evidence_refs'],d"

# Tests
cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/test_ai_router.py tests/test_chat_orchestrator.py tests/test_tool_permissions.py -q
cd apps/web && npm test
```

**Dependencies.** P1 dataset query tool; a provider key or a local OpenAI-compatible runtime for e2e; Keycloak profile. **Risk:** prompt injection, secret handling, tool over-permission. **Mitigation:** tool allowlist, per-tool RBAC, no write tools in v1, encrypted keys, redacted logs. **Estimate:** L.

---

## P3 — Data foundation 2.0 (connectors, jobs, quality, lineage)

**Objective.** Move beyond CSV upload: real read-only connectors, scheduled/incremental ingestion, profiling/quality/lineage, and a data workspace.

**Capabilities delivered.** DATA-03, DATA-06…DATA-09, SURF data workspace, GOV-05 partial, BI-04 (entity/joins foundation).

**Files/modules.**
- Create: `connectors/{base,postgres,mysql,mssql,rest,csv}.py`, `ingestion/jobs.py`, `ingestion/schedule.py`, `profiling/quality.py`, `lineage.py`, tables `data_source`, `connection`, `ingest_job`, `ingest_run`, `data_profile`, `quality_rule`, `lineage_edge`, `entity`, `entity_relationship`.
- Create: worker entrypoint `decisionos_analytics/worker.py` (DB-backed job table; no Kafka/Celery), `api/routers/connectors.py`, `api/routers/jobs.py`, `apps/web/pages/data/index.vue`, `apps/web/pages/data/health.vue`.
- Change: `pipeline.py` to route by format (fix xlsx), `migrations.py` schema v3, `store.py` job helpers, `api.py` upload path to enqueue jobs instead of parsing inline.

**Acceptance commands.**

```bash
# A real Postgres fixture is discovered and ingested incrementally
docker compose -f tests/fixtures/compose.postgres.yml up -d --wait
curl -s -X POST http://127.0.0.1:8100/v1/connectors -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"kind":"postgres","dsn":"postgresql://...","read_only":true}' \
  | python -c "import json,sys;d=json.load(sys.stdin);assert d['status']=='connected'"

# xlsx actually parses
curl -s -X POST .../uploads ... && curl -s .../uploads/$ID/preview | python -c "import json,sys;d=json.load(sys.stdin);assert d['row_count']>0"

# Jobs run in the worker and are observable
curl -s http://127.0.0.1:8100/v1/jobs/$JOB | python -c "import json,sys;d=json.load(sys.stdin);assert d['status']=='succeeded'"
cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/test_connectors.py tests/test_ingestion_jobs.py tests/test_profiling.py -q
```

**Dependencies.** P1 query/artifact contracts; worker deployment. **Risk:** credential storage, SQL injection through connector metadata, long-running jobs. **Mitigation:** read-only roles, query allowlist, credential encryption, bounded rows/time. **Estimate:** L.

---

## P4 — Dashboard builder + artifact system

**Objective.** Real dashboard specifications, persistence, versioning, chart rendering, filters, and AI-generated dashboards from actual data.

**Capabilities delivered.** SURF-02, SURF-07, BI-02 drill/filter, DEC-08 persistence pattern, AI dashboard generation (AI-03 extension).

**Files/modules.**
- Create: `artifacts/dashboards.py`, `artifacts/validate.py` (JSON schema), tables `artifact`, `artifact_version`, `dashboard_component`; `api/routers/dashboards.py`; `apps/web/pages/dashboards/index.vue`, `[id].vue`; `apps/web/components/charts/{Line,Bar,Table,Kpi,Forecast,Anomaly}.vue` using one chart library.
- Change: evidence capture per component; `orchestrator` tool `draft_dashboard`; `apps/web` navigation; `package.json` add chart dependency.
- Reuse: query engine and artifact service from P1; no new rendering math.

**Acceptance commands.**

```bash
# Create, read, version and delete a dashboard
curl -s -X POST http://127.0.0.1:8100/v1/dashboards -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d @fixtures/dashboard.spec.json | tee /tmp/dash.json
DASH=$(python -c "import json;print(json.load(open('/tmp/dash.json'))['id'])")
curl -s http://127.0.0.1:8100/v1/dashboards/$DASH | python -c "import json,sys;d=json.load(sys.stdin);assert d['components'] and d['version']==1"

# Every component has evidence; no hard-coded series
curl -s http://127.0.0.1:8100/v1/dashboards/$DASH/data | python -c "import json,sys;d=json.load(sys.stdin);assert all(c.get('evidence_ref') for c in d['components'])"

cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/test_dashboards.py tests/test_dashboard_spec_validation.py -q
cd apps/web && npm test
```

**Dependencies.** P1, P2 (for NL generation). **Risk:** scope creep into a full BI tool; chart performance. **Mitigation:** fixed component set, server-side query limits, spec validation before render. **Estimate:** L.

---

## P5 — Prediction engine 2.0 (train, evaluate, score, monitor)

**Objective.** Replace the constant score path with real training, persistent model artifacts, evaluation, calibrated scoring, and drift/outcome monitoring.

**Capabilities delivered.** PRED-05, PRED-07, PRED-08…PRED-10, ADAPT-02/03/04, CUST-02 (churn templates).

**Files/modules.**
- Create: `prediction/train.py` (baseline, logistic, RF/GBM; time-based split), `prediction/artifacts.py` (joblib/ONNX + checksum + metrics), `prediction/scoring.py` (load artifact, enforce feature contract), `prediction/drift.py` (PSI/KS, outcome join), `prediction/evaluate.py` (AUC/Brier/calibration), `api/routers/prediction.py`, tables/columns for model artifact + `prediction_outcome` + `model_evaluation` + `drift_report`.
- Change: `api.py` scoring handler to load artifact and reject if absent/not active; `predictive.py` to store artifact ref; `risk.py` classifiers become the implementation behind the interface; `apps/web/pages/risk.vue` to list real scored cases; `apps/web/pages/prediction/index.vue`.
- Remove: `score = 0.65`.

**Acceptance commands.**

```bash
# Train, activate, score two different cases, assert scores differ
curl -s -X POST http://127.0.0.1:8100/v1/predictive/models/$MODEL/train -H "Authorization: Bearer $TOKEN" -d '{"dataset_revision":1,"target":"sla_breach_24h"}'
S1=$(curl -s .../score -d '{"case_id":"A",...}' | python -c "import json,sys;print(json.load(sys.stdin)['score'])")
S2=$(curl -s .../score -d '{"case_id":"B",...}' | python -c "import json,sys;print(json.load(sys.stdin)['score'])")
test "$S1" != "$S2"
curl -s .../predictions/$PID/outcome -d '{"outcome":1}' | python -c "import json,sys;assert json.load(sys.stdin)['status']=='recorded'"

cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/test_prediction_training.py tests/test_scoring.py tests/test_drift.py -q
```

**Dependencies.** P3 for real labelled datasets; P1 for artifact/evidence. **Risk:** insufficient positives, leakage, misleading calibration. **Mitigation:** suitability gate, time-based splits, baseline-first, calibration status surfaced, no score below policy thresholds. **Estimate:** L.

---

## P6 — Knowledge and research (documents, retrieval, case study, competitor)

**Objective.** Ingest authorized documents, retrieve with citations and permissions, and support case-study/competitor research without inventing facts.

**Capabilities delivered.** KNOW-01…KNOW-03, SURF-05, SURF-06, AI tools for retrieval, GOV-05 partial.

**Files/modules.**
- Create: `knowledge/ingest.py` (PDF/Word/text/OCR), `knowledge/chunk.py`, `knowledge/embed.py`, `knowledge/search.py` (keyword + vector + rerank), `knowledge/citations.py`, tables `document`, `document_version`, `chunk`, `embedding`, `research_source`, `case`, `case_finding`, `competitor`, `competitor_finding`; `api/routers/knowledge.py`, `api/routers/cases.py`; `apps/web/pages/knowledge.vue`, `apps/web/pages/cases/[id].vue`, `apps/web/pages/competitors.vue`.
- Change: orchestrator tools `search_documents`, `case_analyze`, `research_public`; evidence model extended for document citations.
- Store: pgvector or a local index; no separate vector service initially.

**Acceptance commands.**

```bash
# Ingest a PDF, retrieve it with a citation, enforce tenant/ACL
curl -s -X POST http://127.0.0.1:8100/v1/knowledge/documents -H "Authorization: Bearer $TOKEN" -F file=@fixtures/policy.pdf
curl -s -X POST http://127.0.0.1:8100/v1/knowledge/search -H "Authorization: Bearer $TOKEN" -d '{"q":"escalation policy","top_k":5}' \
  | python -c "import json,sys;d=json.load(sys.stdin);assert d['results'][0]['citation']['document_id']"
# A user without access gets zero results, not a 404 leak
cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/test_knowledge_ingest.py tests/test_knowledge_search.py tests/test_citations.py -q
```

**Dependencies.** P2 chat/orchestrator; P3 storage. **Risk:** OCR quality, hallucinated citations, ACL leaks. **Mitigation:** citation required on every claim, ACL filter before ranking, “insufficient evidence” outcome. **Estimate:** L.

---

## P7 — Action + adaptive intelligence (approved execution and feedback)

**Objective.** Let users execute permitted actions with approvals and audit, then close the loop with prediction/decision outcome tracking and controlled retraining.

**Capabilities delivered.** ACT-01…ACT-03, ADAPT-02…04, DEC-08 recommendations, ANOM-04 delivery.

**Files/modules.**
- Create: `action/registry.py`, `action/executor.py`, `action/approvals.py`, `action/adapters/{email,webhook,task,report}.py`, tables `action_definition`, `action_run`, `action_approval`; `jobs` dispatcher; `api/routers/actions.py`; `apps/web/pages/actions.vue`.
- Change: `alert_delivery` consumed by a sender; orchestrator tool `propose_action` (draft only), `execute_action` only after approval; prediction outcome job; retraining job + rollback.
- Integrate: decision review → action outcome → adaptive evaluation.

**Acceptance commands.**

```bash
# AI/user can propose but cannot execute without approval
curl -s -X POST .../actions/propose -d '{"kind":"notify","target":"ops"}' | python -c "import json,sys;d=json.load(sys.stdin);assert d['status']=='pending_approval'"
curl -s -X POST .../actions/$ID/execute -H 'Authorization: Bearer '$USER_TOKEN | python -c "import sys,json;d=json.load(sys.stdin);assert d['code']=='approval_required'"
curl -s -X POST .../actions/$ID/approve -H 'Authorization: Bearer '$APPROVER_TOKEN
curl -s -X POST .../actions/$ID/execute -H 'Authorization: Bearer '$USER_TOKEN | python -c "import json,sys;assert json.load(sys.stdin)['status'] in ('succeeded','failed')"

cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/test_actions.py tests/test_approvals.py tests/test_action_audit.py -q
```

**Dependencies.** P5 (prediction outcomes), P6 optional for report actions. **Risk:** unsafe side effects. **Mitigation:** allowlisted adapters, mandatory approval for external effects, dry-run, idempotency keys, full audit. **Estimate:** L.

---

## P8 — Enterprise hardening + industry packs

**Objective.** Make the platform deployable and commercially defensible: Postgres, worker scaling, observability, secrets, audit UI, CVE gates, licence resolution, and configurable industry packs.

**Capabilities delivered.** GOV-05/06/07/09, DATA-09 retention, SURF-09, operational SLAs, multi-tenant admin, pm4py decision, production deployment.

**Files/modules.**
- Migrate control plane to PostgreSQL (`store.py` adapter, Alembic or SQL migrations); keep Parquet/DuckDB analytics.
- Create: `governance/policy.py`, `governance/retention.py`, `api/routers/admin.py`, `api/routers/audit.py`, `industry_packs/{base,banking,retail,ecommerce,healthcare,it,manufacturing}.py`, `packs/*.yaml`.
- Add: OpenTelemetry traces/metrics, Prometheus exporter, Grafana dashboards; secrets backend; field-level encryption; pip-audit/npm audit CI gate; SBOM.
- Resolve pm4py: buy a commercial licence **or** replace `workflow.py` PM4Py usage with an internal DFG/variant implementation; either way keep the process outputs identical (tests are the contract).

**Acceptance commands.**

```bash
# Postgres-backed stack, no SQLite in production profile
docker compose -f docker-compose.prod.yml up -d --wait
curl -s http://127.0.0.1:8100/v1/health | python -c "import json,sys;d=json.load(sys.stdin);assert d['checks']['backend']=='postgres'"

# Security and supply chain gates
pip-audit -r services/analytics/requirements.lock
npm audit --audit-level=high --prefix apps/web
cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests -q --cov=decisionos_analytics --cov-fail-under=85

# Industry pack is configuration, not code fork
curl -s http://127.0.0.1:8100/v1/industry-packs | python -c "import json,sys;d=json.load(sys.stdin);assert {'banking','retail','healthcare'} <= set(d)"
```

**Dependencies.** All prior phases; a business decision on pm4py licensing. **Risk:** migration downtime, licence cost, scope explosion. **Mitigation:** dual-write/migration rehearsal, keep SQLite for tests, ship one industry pack first (support ops is already the de facto pack). **Estimate:** L.

---

## Progress and blockers

| Item | Status | Note |
|---|---|---|
| P1 | Not started | Recommended next |
| P2 | Not started | Needs P1 query tool |
| P3 | Not started | Needs worker; credentials for connector tests |
| P4 | Not started | Needs chart library decision |
| P5 | Not started | Needs labelled data; fake score must be removed first |
| P6 | Not started | OCR/embedding provider decision |
| P7 | Not started | Requires approval policy from owner |
| P8 | Not started | **Blocked on pm4py licence decision** for commercial hosting |

## Explicitly deferred

Cross-company benchmarking, multi-region deployment, streaming ingestion, Spark, Kubernetes, a separate vector database, and a full BI-tool clone. None is justified by current volume; all add operational risk before the core product is trustworthy.
