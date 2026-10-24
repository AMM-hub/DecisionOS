# DecisionOS — Post-Readiness Plan (R7–R12)

**Date:** 2026-10-24
**Basis:** full verification round executed after R1–R6 closed.

## Round results (all re-run today, not inherited claims)

| Check | Command | Result |
|---|---|---|
| Backend suite | `pytest tests -q --cov` | **395 passed, 1 skipped**, coverage **90%** (4219 stmts, 420 miss) |
| Backend lint | `ruff check decisionos_analytics` | **All checks passed** (0 findings) |
| Frontend tests | `npm test` (vitest) | **12 passed** (3 files) |
| Types | `npx nuxt typecheck` | exit 0 |
| Build | `npm run build` | 1.71 MB / 418 kB gzip |
| UI sweep | `node scripts/ui_audit.mjs` | **52/52 configs clean** (0 console errors, 0 exceptions, 0 bad values) |
| Live API | `scripts/live_api_probe2.py` | 13/14 (last item was a probe bug — fixed) |
| Live latency | — | p50 3 ms, p95 4 ms, max 62 ms |
| Compose syntax | `docker compose config` | valid |
| Docker engine | `docker info` | **daemon down** — no image ever built |

## What actually remains

**P1 · Containers have never run.** Dockerfiles and compose exist and validate, but no image has been
built or started. "It runs in compose" is currently a claim, not a fact.
**P2 · CI has never executed.** The repo is **55 commits ahead** of `origin/main` (0 behind). The workflow
file has never been pushed, so no run exists. `gh` CLI is not installed.
**P3 · No schema migrations.** `store.py` issues 31 `CREATE TABLE IF NOT EXISTS` statements at boot.
There is no schema_version, no forward migration path, no downgrade story. Any column change on a live
pilot database is undeployable.
**P4 · No operational instrumentation.** No rate limiting (a single client can exhaust the SQLite writer),
no structured/JSON logging, no request IDs, no metrics endpoint. `GET /v1/health` returns a constant and
never touches the database — it reports "ok" even if the DB file is corrupt.
**P5 · No backup/restore.** No VACUUM, no snapshot script, no documented restore. SQLite is single-writer;
that is acceptable for pilot volume but must be stated and instrumented, not discovered later.
**P6 · No identity provider.** Token minting is now off by default and boot refuses weak secrets — good —
but nothing issues tokens. There is no OIDC flow, so a real deployment has no way to log a human in.
**P7 · E2E is not in CI.** The 52-config browser sweep runs only when a human types the command.
**P8 · Cold-start experience.** A fresh database renders empty states everywhere with no seed path
(only `scripts/e2e_demo.py`). First-run demo requires hand-holding.

## Plan

### R7 · Containers actually run  (P1)
Build both images, `docker compose up -d`, wait for health, then prove: `/v1/health` 200 from the api
container, `/` 200 from the web container, and a real decision created through the containerised stack.
Tear down cleanly. Fix whatever breaks (likely: sqlite volume permissions, `DECISIONOS_DATA_DIR` path,
nuxt build output path, node user).

### R8 · CI green on the real remote  (P2)
Push `main` to `origin` (fast-forward, 55 commits, no force), then observe the workflow run through the
GitHub API and report the actual conclusion. If auth blocks it, report exactly which credential is needed.

### R9 · Operational hardening  (P4, P5)
- Deep health: `/v1/health` performs `PRAGMA quick_check` + schema version + writable probe; returns 503
  with a reason when unhealthy.
- Request IDs: accept/propagate `X-Request-Id`, include it in every log line and error body.
- Structured JSON logging with level and latency per request.
- Token-bucket rate limit per tenant (in-process, documented as single-node).
- `/v1/metrics` counters: requests, errors by code, p50/p95 buckets.
- `scripts/backup_db.py`: `VACUUM INTO` snapshot + `PRAGMA integrity_check`, timestamped, with restore docs.

### R10 · Schema migrations  (P3)
`store.py` gains a `schema_version` table and an ordered migration list; boot applies pending migrations
inside a transaction and refuses to start if the DB is newer than the code. Add a test that migrates a
v0 database forward.

### R11 · E2E in CI  (P7)
Add a job that builds the app, boots api+web, runs `scripts/ui_audit.mjs` against them, and fails on any
console error, exception, bad value, or document overflow. Upload the 52 screenshots as artifacts.

### R12 · Identity + cold start  (P6, P8)
- Compose profile `auth`: Keycloak with a DecisionOS realm, OIDC client, and the API validating
  `iss`/`aud`/`exp` from the realm's JWKS.
- `scripts/seed_demo.py`: idempotent seed (tenant, workspace, members, dataset, published metric,
  a few decisions) so a fresh install has a coherent demo in one command.

## Sequencing
```
R7 (containers) ─┬─> R8 (CI) ──> R11 (E2E in CI)
R9 (ops) ────────┤
R10 (migrations) ┘
R12 (identity/seed) — independent, after R7
```

Exit criteria for "deployable": `docker compose up` green on a clean machine, CI green on GitHub,
health endpoint tells the truth, a schema change ships as a migration, and a human can log in.

## Log

**2026-10-24 — round executed.** All code-level checks green; the gaps are delivery-level.

**R7 CLOSED — containers run.** `docker compose build` + `up -d` succeeded (Docker Desktop started).
Proof: api container `/v1/health` 200 in 21 ms, anonymous `/v1/decisions` 401, authenticated 200;
web container `/` and `/risk` 200; **full 52-config UI sweep re-run against the containerised stack,
0 console errors / 0 exceptions / 0 bad values**. Local dev servers were stopped first to free
:8100/:3000 — the stack is currently served by containers.

**R8 CLOSED — CI is real and green.** `main` was 55 commits ahead of `origin`; pushed (fast-forward).
First run **failed**, which was the point of doing it:
- `simulation.py` / `optimization.py` import `simpy`, `pulp`, `pm4py` — **none were declared** in
  `pyproject.toml`. A clean install could not even collect tests. The dev venv had them by accident.
- `pulp` had also drifted to 4.x in the clean environment, which removed the `LpStatus*` constants the
  solver module uses. Pinned `pulp>=2.9,<4`.
Verified in a clean `python:3.12-slim` container: 395 passed, coverage 90.05%. Pushed as `67c7e60`;
**CI run 67c7e60 = success (backend + frontend)**.

**NEW RISK (P9) — licensing.** `pm4py` is **AGPL v3**: the banner states commercial use requires
open-sourcing the application or buying a commercial licence. The process-mining endpoints depend on it.
If DecisionOS is to be sold or hosted commercially, this must be resolved (licence purchase or replace
with a permissive implementation). Flagged now, not at contract-signing time.

Remaining open: **R9** (ops hardening), **R10** (migrations), **R11** (E2E in CI), **R12** (identity + seed).
