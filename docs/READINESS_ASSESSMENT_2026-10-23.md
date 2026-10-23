# DecisionOS — Real Readiness Assessment

**Date:** 2026-10-23
**Assessor:** Hermes (controller) — independent of Antigravity's own QA runs
**Scope:** live services on this machine, black-box HTTP probing, 296-test regression run,
52-config browser sweep (13 routes × 2 viewports × 2 locales), static analysis, build/deploy surface.
**Commit under test:** `1c5398d` (audit harnesses checkpointed at `3dd398a`)

---

## 1. Verdict

| Dimension | State | Judgment |
|---|---|---|
| Functional depth (API surface) | 81 operations / 71 paths, decision state machine, pilot, predictive, workflow, scenarios, evidence | **Strong** |
| Backend correctness | 296/296 tests pass, 90% statement coverage | **Strong** |
| API contract quality | 45 endpoints emit a double-encoded error body; 404 used for payload errors | **Broken** |
| Auth / multi-tenancy | demo headers, unauthenticated token minting, hardcoded fallback signing secret | **Not production-safe** |
| Frontend build & types | `nuxt typecheck` 0 errors, `nuxt build` 1.71 MB (418 kB gzip) | **Strong** |
| Frontend behaviour | 52/52 route×viewport×locale loads, 0 console errors, 0 exceptions, i18n 149/149 parity | **Strong** |
| Frontend responsiveness | `/risk` 9-column table escapes the viewport at 1366×768 (actions unreachable) | **Defect** |
| Frontend test coverage | 0 tests, 0 test runner configured | **Missing** |
| CI / deploy packaging | no `.github`, no compose file, no `.env.example`, services started by hand | **Missing** |
| Scale readiness | no pagination/filtering on any list endpoint | **Blocker** |

**One-liner:** this is a genuinely capable, well-tested *demo/pilot* platform. It is **not** a
production-ready product yet. The gap is not features — it is the four "boring" layers a real
deployment dies on: auth, error contract, pagination, and repeatable delivery.

Readiness score against a strict production gate: **~55%**. Against "impressive internal pilot": **92%**.

---

## 2. What actually passed (live evidence)

- `GET /v1/health` → 200, p50 API latency **3 ms**, p95 **21 ms**, max 43 ms over 30 calls.
- Auth boundary: anonymous → 401; synthetic tenant `test-tenant` → 401; unknown route → 404.
- Full decision lifecycle executed live: `draft → proposed → accepted → implementation_pending →
  active → review_due → evaluated`, outcome recorded with `supported_improvement`, outcome-comparison
  endpoint returns 200. Illegal transition rejected with 409.
- Read surface: datasets, decisions, investigations, pilots, metric definitions, monitoring
  rules/episodes/conditions, predictive models/targets, scenario templates, semantic pack, job outbox
  — all 200.
- Backend: **296 passed in 66.32 s**; coverage **90%** (api.py 89%, register.py 100%, evidence.py 100%).
- Frontend: typecheck clean; production build clean; 52 config sweep with **zero console errors**;
  Arabic RTL flips correctly; numbers/IDs keep LTR; i18n key parity 149/149.

## 3. Defects found (ranked)

### P0 — must fix before any real deployment

**P0-1 · Auth is decorative.**
- `POST /v1/auth/token` mints a valid JWT for **any** tenant/user/role with **no authentication**.
- `security.py:20` ships a hardcoded fallback signing secret
  (`decisionos-production-control-plane-secret-key-32b-min`); if `DECISIONOS_JWT_SECRET` is unset,
  every token is forgeable.
- Demo `X-Tenant` / `X-User` headers are accepted unless `DECISIONOS_AUTH_STRICT=1` — the default is off.
- Net effect: tenant isolation is enforced by convention, not by crypto.

**P0-2 · Error contract is broken on 45 endpoints.**
`raise HTTPException(422, json.dumps({"code": ..., "detail": ...}))` makes FastAPI wrap the string, so
clients receive:
```json
{"detail": "{\"code\": \"invalid_decision\", \"detail\": \"'brief'\"}"}
```
A machine-readable `code` becomes a nested string — every SDK/client must double-parse. The Nuxt client
(`composables/api.ts`) already works around it.
Worse: payload-shape errors return **404** (`{'detail': "'review_verdict'"}` / `'evidence_id'`), because
`except LookupError -> HTTPException(404, str(e))` also catches plain `KeyError`. A missing field is not
"not found", and Python exception text leaks to the client.

**P0-3 · No pagination anywhere.**
No `limit`/`offset`/`cursor` parameter exists on any endpoint in the OpenAPI document. `/v1/decisions`,
`/v1/datasets`, `/v1/monitoring/episodes` return everything. Fine at 4 rows; fatal at 40,000.

**P0-4 · Not deliverable twice.**
No CI pipeline, no `docker-compose.yml`, no `.env.example`, no migration story (schema created at boot).
The app only runs because two dev servers happen to be up on this laptop.

### P1 — quality / credibility

**P1-1 · `/risk` table escapes the viewport.** 9 columns, no scroll container: at 1366×768 the table
extends to x=1462 and the `QUALITY / SUITABILITY` and `ACTIONS` columns are unreachable (in AR it
overflows to x=-23). Measured on both locales.
**P1-2 · Raw ISO timestamps rendered inline** (`2026-10-05T14:00:00Z`) and wrapping mid-token across
three lines in narrow cells.
**P1-3 · Breadcrumb mismatch**: `/pilot` renders breadcrumb "Pilot Setup" above the heading
"Executive Pilot Command Center".
**P1-4 · Lint debt**: 98 ruff findings (26 unused imports, 19 unsorted imports, 10 blind `except Exception`).
**P1-5 · Dead surface**: `apps/api` (Laravel, 36-line API) is not referenced by the web app and is not running.
**P1-6 · Audit false positive**: the UI probe flags `null` on `/metrics` — that string lives inside a
JSON metric definition (`is_not_null`), not a rendering bug. Probe needs token-aware matching.

## 4. Interpretation

The engineering done so far (master spec, certification reports, phase gates) is real and the
implementation honours it. What is missing is everything that only shows up when someone other than
the author runs it: a real identity provider, a stable error contract, bounded responses, reproducible
delivery, and tests on the half of the product that users actually touch (the browser).

---

## 5. Remediation plan

See `docs/REMEDIATION_PLAN.md`. Six gates, each with an executable acceptance test; no gate is
"done" on a claim — only on a green command.
