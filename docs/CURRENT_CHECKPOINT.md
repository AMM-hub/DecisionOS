# DecisionOS — Current Checkpoint

**Date:** 2026-10-25 · **Commit:** `98da645` · **Phase:** P0–P2 complete, **P3a complete**, P3b in progress · **Mode:** single-node pilot
**Schema:** v6 (`data_foundation`) · **API:** 98 paths / 119 operations

## State in one sentence

A tested operational decision-intelligence pilot that now ingests from real databases instead of
only CSV, and whose multi-agent AI workspace answers only from computed tool results — but it still
has no dashboard builder, no training pipeline for prediction, and no commercial licence for the
PM4Py workflow engine.

## Verified working (commands re-run today, this machine)

- Backend: **458 passed, 6 skipped** —
  `cd services/analytics && env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests -q`
  (the 6 skips are the live-PostgreSQL tests, run separately below).
- Lint: **clean** — `... -m ruff check decisionos_analytics`.
- Live PostgreSQL tests: **5 passed** with
  `DECISIONOS_TEST_PG_DSN=postgresql://decisionos_ro:...@127.0.0.1:5432/decisionos_fixture`
  and `DECISIONOS_TEST_PG_ADMIN_DSN=postgresql://postgres:...` — real connection, table listing,
  bounded reads, read-only refusal, and a create/insert/read/drop round trip.
- End-to-end against real PostgreSQL 18, **28/28 checks** (`.agents/verify_p3_e2e.py`, every expected
  value derived from SQL, never from the API): connector create → `test` → table discovery →
  bounded preview → ingest job → worker run → published dataset → query grouped counts identical to
  SQL (60/60/60/60) with an `evidence_ref` → profile identical to SQL (`null_rate` 0.5000,
  `distinct_count` 4) → `not_null` passes → `range` fails with exactly 85 violations →
  incremental run ingests exactly the 24 rows past the watermark and advances it → no secret in any
  response.
- Frontend: **33 passed** — `cd apps/web && npx vitest run`; `npx nuxt typecheck` exits 0;
  `npx nuxt build` completes (1.72 MB server bundle).
- Local install: `bash run-local.sh` cold-start verified on a throwaway data dir — API up, demo
  seeded through the public HTTP contract, console up, banner printed.
- Live AI path: `/intelligence` answered grounded questions with a real DeepSeek call, returned a
  correct grouped table, surfaced `3 tool calls · 1 evidence ref` and real per-turn usage.

## What each phase delivered

| Phase | Delivered |
|---|---|
| P0 | Audit of the codebase against the master directive (7 checkpoint artifacts) |
| P1a | All fabricated analytics removed; refusal is the contract (`POST /v1/predictive/score` and `outcome-comparison` no longer invent values) |
| P1b | Bounded dataset query over a published revision, saved analyses, Analytics Studio |
| P2a | Provider registry with encrypted keys, tool-bound agent (`list_datasets`, `dataset_schema`, `analytics_query`, …), chat API, usage accounting |
| P2b | `/intelligence` chat (tool trace, evidence refs, ungrounded-number banner) and `/settings/ai` (provider table, six model roles, usage) |
| P3a | Connectors (PostgreSQL, REST), DB-backed ingestion worker, profiling/quality rules, xlsx parsing, schema v6 |

## In progress

**P3b — `/data` workspace UI.** Sources (test/browse/delete), ingest jobs with live run polling,
quality panel with real observed counts. Prompt at `.agents/p3b_frontend_prompt.md`; backend
contract already live.

## Known gaps

| Gap | Impact | Phase |
|---|---|---|
| pm4py **AGPL v3** | Commercial hosting needs a licence or a replacement engine | Business decision (ADR-006) |
| No scheduled ingestion | Jobs run on demand only; `schedule_cron` is stored but nothing executes it | P3 remainder |
| Only PostgreSQL + REST connectors | MySQL/MSSQL/csv-connector and live REST verification outstanding | P3 remainder |
| No lineage/entity graph | `lineage_edge`, `entity`, `entity_relationship` not implemented | P3 remainder / P4 |
| No SPA login (OIDC) | Strict-auth deployments cannot use the browser UI | P2 remainder |
| No labelled training data | Real risk scores remain refused rather than faked | P5 |
| No dashboard builder | Analyses are saved but not composable into dashboards | P4 |

## Truth invariants (must stay true)

1. No user-visible number exists that did not come from a computed query, with an `evidence_ref`.
2. Any surface that cannot compute a value refuses with a documented code — it never renders a
   placeholder that looks measured.
3. Connector credentials are encrypted at rest, never returned, never logged.
4. Every table read is tenant-scoped.

## Next 3 tasks

1. **Finish P3b** (`npm test`, `nuxt typecheck`, `nuxt build`) and screenshot `/data` in EN and AR.
2. **Scheduled ingestion** — a cron field on `ingest_job` evaluated by the worker; acceptance:
   a job with `schedule_cron: "*/1 * * * *"` enqueues a run within 90 s with no HTTP call.
3. **REST connector live verification** — point at a real HTTP JSON endpoint and prove
   `test_connection`, preview and ingest, including the pagination cap.
