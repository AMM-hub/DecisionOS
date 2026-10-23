# DecisionOS — Remediation Plan (Production Readiness)

Derived from `docs/READINESS_ASSESSMENT_2026-10-23.md`.
Execution model: **Hermes controls, Antigravity (Claude Sonnet 4.6 / Opus 4.6) implements.**
Every gate closes only on a green command listed under *Prove it*.

---

## R1 · Machine-readable error contract  (P0-2)
**Owner:** Antigravity · Sonnet 4.6 · **Scope:** `services/analytics/decisionos_analytics/api.py`, `security.py`, `apps/web/composables/api.ts`

1. Add one helper in `api.py`:
   `api_error(status: int, code: str, detail: str, extra: dict | None = None) -> JSONResponse`
   returning `{"code": ..., "detail": ..., "status": status}` with `Content-Type: application/json`.
2. Replace **all 45** `HTTPException(<4xx>, json.dumps({"code": ...}))` sites with it (keep genuine
   `HTTPException` for plain 401/403/404 where there is no code payload).
3. Fix exception→status mapping everywhere:
   `KeyError/TypeError/ValueError` → **422** with `code` (`missing_field`, `invalid_value`);
   `LookupError` from store only → **404**; `sqlite3.IntegrityError` → **409**.
   No Python exception text may reach the client — map to a stable message, log the original.
4. Guarantee: no response body ever contains a JSON-encoded string inside `detail`.
5. Update `apps/web/composables/api.ts` to read `code`/`detail` from the flat shape (keep back-compat
   for the nested string form during rollout).
6. Add `tests/test_error_contract.py`: drive every mutating endpoint with (a) missing field, (b) wrong
   type, (c) unknown id; assert status, `code` present, `detail` is a string, and `detail` never parses
   to JSON.

**Prove it:** `pytest tests -q` green · `python scripts/live_api_probe2.py` → 0 failures.

---

## R2 · Real authentication & tenant isolation  (P0-1)
**Owner:** Antigravity · Opus 4.6 · **Scope:** `security.py`, `api.py`, `tests/`

1. Delete the hardcoded fallback: if `DECISIONOS_AUTH_STRICT=1` and `DECISIONOS_JWT_SECRET` is unset
   (or < 32 bytes), the process **refuses to boot** with a clear message.
2. Gate `POST /v1/auth/token` behind `DECISIONOS_ALLOW_TOKEN_MINT=1` (default off). In strict mode it
   returns 404, not 200.
3. In strict mode, `X-Tenant`/`X-User` headers must be **ignored** (not merely unverified) — identity
   comes from the JWT only.
4. Enforce RBAC per route with `ROLE_PERMISSIONS`: map each mutating route to a permission and return
   **403** with `code: "forbidden"` when the role lacks it (e.g. `semantic_modeler` cannot approve a
   metric, `ops_manager` cannot self-approve — extend the existing §29 QA-018 rule).
5. Add `tests/test_auth_strict.py`: forged signature → 401; expired token → 401; tenant mismatch → 403/404;
   demo headers in strict mode → 401; missing secret in strict mode → boot failure; role matrix table
   test over every mutating route.

**Prove it:** `DECISIONOS_AUTH_STRICT=1 pytest tests -q` green, plus a live run with strict mode on:
`curl` with demo headers → 401, with minted JWT → 200.

---

## R3 · Bounded list endpoints  (P0-3)
**Owner:** Antigravity · Sonnet 4.6 · **Scope:** `api.py`, list handlers in `store.py`/modules

1. Add `limit: int = Query(50, ge=1, le=500)` and `offset: int = Query(0, ge=0)` to every `GET` list
   endpoint (decisions, datasets, investigations, evidence, monitoring rules/episodes/conditions,
   predictive models/targets, pilots, metric definitions, outbox, uploads).
2. Response stays a bare JSON array (back-compat) **plus** `X-Total-Count` header; document both.
3. Add `q=` substring filter where a human list exists (decisions title, investigations title, datasets name).
4. Add `tests/test_pagination.py`: default cap applied, `limit`/`offset` respected, `X-Total-Count`
   correct, out-of-range rejected with 422 and `code: "invalid_pagination"`.

**Prove it:** `pytest tests -q` green · OpenAPI shows the params on every list path.

---

## R4 · Frontend correctness & polish  (P1-1, P1-1b, P1-2, P1-3)
**Owner:** Antigravity · Sonnet 4.6 · **Scope:** `apps/web/pages/risk.vue`, `app.vue`, `composables/format.ts`

0. **Correction:** `.table-scroll` already exists and works — measured 951px client vs 1189px scroll with
   zero document overflow. Do NOT re-wrap. The table is *not* broken.
1. **Remove the fabricated rows.** `pages/risk.vue` falls back to 12 hardcoded literals (CASE-8021 etc.)
   when the predictive API returns no cases. Replace with the shared `.empty` state ("No cases scored yet
   — connect a predictive target") plus a CTA. If a demo seed is wanted, gate it behind an explicit
   `?demo=1` and label it visibly.
2. **Make the horizontal scroll discoverable:** sticky CASE ID column and an edge fade while
   `scrollWidth > clientWidth`.
3. Format the SLA deadline through `formatDateTime(iso, locale)` — never render raw ISO; keep the value
   LTR-isolated in RTL mode.
4. Fix the breadcrumb map: `/pilot` must read "Pilot Center" (`nav.pilotDashboard`), not "Pilot Setup".
5. Re-run the sweep: `/risk` reports no raw ISO, no `undefined`/`NaN`, 0 console errors in EN and AR.

**Prove it:** `node scripts/ui_audit.mjs` → 0 bad values, 0 console errors, 0 exceptions across 52 configs.

## R5 · Frontend test harness + CI  (P0-4, missing FE tests)
**Owner:** Antigravity · Sonnet 4.6 · **Scope:** `apps/web`, `.github/workflows/ci.yml`

1. Add `vitest` + `@vue/test-utils` + `happy-dom`; `npm test` must run headless.
2. Minimum suite: `format.ts` (currency/percent/date/RTL-safe numbers), `api.ts` error mapping (flat +
   nested detail), one component smoke test per page that mounts with mocked `$fetch`.
3. `.github/workflows/ci.yml`: jobs `backend` (ruff + pytest + coverage ≥ 85), `frontend`
   (typecheck + vitest + build). Fails on any red.
4. Add `.env.example` (both services) and a `docker-compose.yml` running api+web with a shared volume.

**Prove it:** `npm test` green · `ruff check` clean · workflow file lints · `docker compose config` valid.

---

## R6 · Repo hygiene & decision record  (P1-4, P1-5, P1-6)
**Owner:** Antigravity · Gemini 3.8 Flash (cheap sweep) · **Scope:** repo-wide

1. `ruff check --fix` + manual fix of the 10 blind excepts (narrow to expected types or log-and-reraise).
2. Archive or delete `apps/api` (Laravel): move to `archive/apps-api/` with a README note, or delete —
   no half-dead service in the tree.
3. Harden `scripts/ui_audit.mjs` bad-value detection to whole-word matching so `is_not_null` stops
   flagging `null`.
4. Update `PROJECT.md` + `README.md` to reflect strict-auth boot requirements and the new pagination contract.

**Prove it:** `ruff check` → 0 · `node scripts/ui_audit.mjs` → 0 bad values · docs updated.

---

## Sequencing & gates

```
R1 (contract)  ─┬─> R3 (pagination) ─┬─> R5 (CI)  ──> R6 (hygiene)
R2 (auth)      ─┘                    │
R4 (UI) ─────────────────────────────┘
```

R1 and R2 are independent and can run in parallel; R3 depends on R1's error helper; R5 gates the
"done" claim; R6 is cleanup that must not regress the others.

**Exit criteria for "production ready":** R1–R6 closed, CI green on a clean clone, strict auth boot
proven, 52/52 UI sweep clean, and `docker compose up` serving both services from a fresh machine.
