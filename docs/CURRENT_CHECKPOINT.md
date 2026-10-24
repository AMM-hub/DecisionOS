# DecisionOS — Current Checkpoint

**Date:** 2026-10-24 · **Commit:** `121689c` · **Phase:** 0 complete → **P1 not started** · **Mode:** single-node pilot

## State in one sentence

A well-tested operational decision-intelligence pilot (CSV → grain → certified metrics → evidence → forecast → process → optimisation → decision) that is **not yet a universal intelligence platform** and currently shows invented numbers in three user-visible places.

## Verified working (commands re-run today)

- Backend: **415 passed, 1 skipped** — `cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests -q`.
- Lint: **clean** — `... -m ruff check decisionos_analytics`.
- Frontend: **17 passed** — `cd apps/web && npm test`.
- Live API: **72 paths / 82 operations** — `curl -s http://127.0.0.1:8100/openapi.json`.
- Live storage: schema **v2**, **27 domain tables** + `schema_version` — queried `var/worker/control.sqlite3` and the container volume.
- Containers: `api`, `web`, `keycloak` running; health `{"status":"ok","schema_version":2,"writable":true}`.
- CI: 3 jobs (backend, frontend, e2e); run `121689c` green per controller evidence; 52-config sweep `FAILURES: 0`.
- Implemented domain spine: upload/scan/parse/grain/revision/publish; versioned metric definitions; Polars metric query; evidence with digest verification; StatsForecast with refusal + baseline-first selection; PM4Py workflow analytics; PuLP solver; SimPy simulation; anomaly rules/episodes; decision register + outcome review; HMAC/OIDC auth; RBAC; migrations; deep health; seed.

## In progress

Nothing is mid-implementation. Phase 0 documentation is complete; the code tree is unchanged from `121689c`.

## Blocked / unresolved

| Blocker | Impact | Owner action |
|---|---|---|
| pm4py **AGPL v3** | Commercial hosting needs a licence or replacement | Business decision; options in ADR-006 |
| No SPA login / OIDC | Strict-auth deployments cannot use the product from the browser | P2; ADR-010 must be superseded |
| No labelled training data pipeline | Real risk scoring cannot be trained | P3/P5 |
| Provider keys / local model runtime | AI workspace cannot be exercised end-to-end | P2 prerequisite |
| No connector credentials | Postgres/MySQL/MSSQL/REST ingestion cannot be verified | P3 prerequisite |

## Known defects that invalidate trust (P0)

1. `POST /v1/predictive/score` returns constant `0.65` (`api.py:1812`).
2. `GET /v1/decisions/{id}/outcome-comparison` returns hard-coded values and verdict (`api.py:2346-2388`).
3. Pilot page renders static SVG telemetry `94.2% / 92.0% / T+38h` (`pilot/index.vue:110-222`).
4. `/risk` never loads a queue (`risk.vue:257`) and its actions use a duplicated `/v1` prefix (`risk.vue:273,284`).
5. Evidence stores literal `definition_version=1` (`evidence.py:174`), mislabelling v2+ provenance.

## Next 3 tasks (with acceptance commands)

**1. Remove fabricated analytics and make refusal the contract.**
- Files: `api.py` (score + outcome comparison), `pilot/index.vue`, `risk.vue`, tests.
- Acceptance:
```bash
grep -R "score = 0.65" services/analytics/decisionos_analytics && exit 1 || true
grep -R "94.2%\|T+38h\|18.5" services/analytics/decisionos_analytics apps/web/pages && exit 1 || true
cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests -q
```

**2. Add a read-only dataset query + evidence (P1 core).**
- Files: `decisionos_analytics/analytics/query.py`, `api/routers/analytics.py` (or `api.py`), migration if needed, `tests/test_dataset_query.py`.
- Acceptance:
```bash
curl -s -X POST http://127.0.0.1:8100/v1/datasets/$DS/query \
  -H 'X-Tenant: tenant_alpha' -H 'X-User: alpha.manager' -H 'Content-Type: application/json' \
  -d '{"select":["status"],"aggregate":[{"fn":"count","as":"n"}],"group_by":["status"]}' \
  | python -c "import json,sys;d=json.load(sys.stdin);assert d['rows'] and d['evidence_ref'];print(d['rows'][:2])"
cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/test_dataset_query.py -q
```

**3. Add the chart + saved-analysis artifact surface.**
- Files: `apps/web/pages/analytics.vue`, `components/Chart.vue`, `artifacts.py` + `artifact` table, `api/routers/artifacts.py`.
- Acceptance:
```bash
cd apps/web && npm test && npx nuxt typecheck
curl -s http://127.0.0.1:8100/v1/artifacts -H 'X-Tenant: tenant_alpha' -H 'X-User: alpha.manager' \
  | python -c "import json,sys;a=json.load(sys.stdin);assert any(x['type']=='analysis' for x in a)"
```

## Single most valuable thing to do next

**Delete the three fabricated analytics surfaces, then ship the P1 Analytics Studio slice (dataset query → chart → saved evidence-backed analysis).** The platform's differentiator is trustworthy evidence; every new AI/dashboard feature built before this fix will faithfully explain numbers that were never computed. The full phase plan is in `docs/ROADMAP.md` P1.
