# DecisionOS

Monorepo implementing the corrected master specification
(`DecisionOS_Master_Business_and_Technical_Specification.md`). All data is
synthetic; no values come from any real customer.

## Layout

| Path | Role |
|---|---|
| `apps/web` | Nuxt 3 + TypeScript workspace SPA (pinned `nuxt@^3.21`) |
| `apps/api` | Laravel 13 application API skeleton — identity, policies, artifact lifecycle, job coordination, audit (spec §21.2). Requires PHP/Composer to materialize. |
| `services/analytics` | Python bounded workers: safe parsing, profiling, grain proof, plan compilation, metric execution (Polars + Pydantic + FastAPI). Runnable today. |
| `packages/contracts` | Versioned OpenAPI + JSON Schemas (event envelope §23.6, job attempt §23.5) |
| `fixtures/support-tickets` | Two-tenant synthetic ticket corpus + adversarial file + independently computed golden manifest |
| `infra/docker-compose.yml` | PostgreSQL 17, Redis, MinIO, api, worker, web |

## The E2E spine (built and verified)

`authorized upload → quarantine scan → bounded parse → profile → grain candidates
proven over full data → human grain confirmation → atomic revision publication
(manifest + outbox) → metric propose → approve (different actor) → certified
query → golden-checked answer + persisted evidence`

Run it:

```bash
# tests (20 passing, includes golden comparison + refusal paths)
cd services/analytics && .venv/Scripts/python -m pytest --basetemp=.ptmp

# narrated demo
python scripts/e2e_demo.py

# serve the control plane for the Nuxt frontend (demo stand-in for the Laravel API)
.venv/Scripts/python -m uvicorn decisionos_analytics.serve:app --port 8100
cd apps/web && npm run dev   # set NUXT_PUBLIC_API_BASE=http://127.0.0.1:8100/api/v1
```

## Honesty notes (deliberate, tracked)

- No PHP/Composer on this machine and the Docker daemon was unavailable, so the
  Laravel app is a hand-written skeleton; the Python service carries the
  executable pipeline and doubles as the local `/v1` control plane for demo/tests.
  Production authority stays with Laravel per §21.2 — the Python store is not the
  metadata system of record.
- Tenant context in the demo control plane uses `X-Tenant`/`X-User` headers; the
  Laravel middleware has the same hook gated to `local` + explicit env flag.
- XLSX parsing, rate limiting, and the lease sweeper are scaffolded with limits
  and tests for CSV first; XLSX formula/cache semantics (§8.2) are on deck.
- GiST exclusion for nonoverlapping publication intervals (§22.3) ships with the
  Postgres migrations, not the SQLite demo store.

## Fixtures

Regenerate deterministically (`SEED=20260915`):

```bash
python fixtures/support-tickets/generate.py
```

- `tenant_alpha` (Northline Telecom, synthetic): 420 cases + event history + agents
- `tenant_beta` (Harbor Retail Bank, synthetic): 130 cases + history
- `adversarial/`: leading-zero ids, ambiguous `03/04/2026`, duplicate + null key
  rows, formula-injection cells, malformed row (QA-001/002/005)
- `data/manifest.json`: per-branch eligible/responded counts and medians computed
  independently of the pipeline — the golden answers tests must reproduce.
# DecisionOS
