# DecisionOS — UI Overhaul Plan

**Date:** 2026-10-24 · **Trigger:** user review screenshot — "the UI is sooo bad"

## What is actually wrong (diagnosed, not guessed)

### U1 · i18n is broken in production builds — CRITICAL
`composables/locale.ts` keeps messages in a module-level `let messages` and fills them with an **async
`fetch('/locales/en.json')`**. `t()` is **synchronous** and returns the key when `messages` is still null,
and `messages` is not reactive, so a late load can never repaint.
`app.vue` does a top-level `await loadMessages(...)`, which works under the dev server but not in the
production SPA build — so every chrome string renders as a raw key: `common.appName`, `nav.home`,
`nav.pilotDashboard`, `NAV.GROUPCOMMAND`.
Evidence: live container, `document.body.innerText` shows `common.appName / nav.home / nav.*`.
The JSON files themselves serve fine (`/locales/en.json` → 200). It is a load-ordering bug, not a missing asset.

### U2 · The design system exists; the pages ignore it
`app.vue` defines a complete token set: `.card` + `.card-header` + `.card-body`, `.kpi-band` + `.kpi`,
`.empty` + `.e-ico`, `.table-foot`, `.segmented`, `.btn`, `.chip`, `.drawer`, `.modal`.
Seven pages bypass it and put raw `<h2>`/numbers straight inside `.card`, so content has **no padding**,
headers sit flush on the border, and numbers use `.stat .n` (1.8rem) instead of `.kpi .k-val`:

| page | bare `.card` | uses `card-header`/`card-body` |
|---|---|---|
| datasets.vue | 2 | 0 |
| forecasts.vue | 6 | 0 |
| index.vue | 3 | 0 |
| metrics.vue | 5 | 0 |
| scenarios.vue | 4 | 0 |
| uploads.vue | 5 | 0 |
| workflow.vue | 7 | 0 |
| pilot/setup.vue | 1 | 0 |
| decisions.vue | 0 | 3 ✓ |
| monitoring.vue | 0 | 10 ✓ |
| investigations/*.vue | 0 | 3–10 ✓ |

### U3 · Overview page is structurally wrong
Three equal cards where the third crams a full timestamp (`10/24/2026, 6:59:47 PM`) into a 1.8rem numeral —
the one element a KPI band must never do. No 4th metric, no status strip, no action priority, and the
"Getting started" list is a flat `<ol>` with no sense of progress.

### U4 · Dates and numbers are inconsistent
`new Date(iso).toLocaleString()` (US month/day, seconds) in index.vue, while `composables/format.ts`
already provides `formatDate` / `formatDateTime` / `shortId` / `titleCase` used correctly by `/risk`.
Same data renders three ways across pages.

### U5 · No guard rails
Nothing fails when i18n breaks or when a page ignores the card contract, so this can regress silently.
`ui_audit.mjs` checks console errors and layout overflow but not "is the chrome showing raw keys".

## Plan

### U-A · i18n, made impossible to break
- Import `locales/en.json` and `locales/ar.json` **statically** (`import en from '~/locales/en.json'`), delete
  the runtime `fetch` and the async init, keep `t()` synchronous and pure.
- Make the locale a real reactive ref so switching EN/AR repaints immediately (including `<html dir>`).
- Keep the `t(key, locale)` call shape so 13 pages do not need rewriting.
- Delete the duplicate `public/locales/*` copies (single source of truth).

### U-B · One page shell, used everywhere
Add `components/PageHeader.vue` (title / subtitle / actions slot) and `components/DcCard.vue`
(`.card` + `.card-header` + `.card-body`, optional `#actions`).
Convert the 8 offending pages to `<DcCard>` and `<PageHeader>`. No page may put content directly inside
`.card` again.

### U-C · Overview page redesign
- `.kpi-band` with **4** tiles: Datasets (with published/grain-confirmed subtitle), Certified metrics
  (of N definitions), Open decisions (by status chips), Monitoring alerts (episodes open).
- Two-column body: left "Next actions" checklist (4 steps, each with state done/pending + link),
  right "Recent activity" table using `formatDateTime` + relative age.
- Empty, loading (skeleton rows), and error (banner + Retry) states for each panel.

### U-D · Consistency sweep
- Every date via `format.ts`; no `toLocaleString()` in pages.
- Every list page gets the same toolbar pattern (search / filter / primary action) and `.table-foot`
  with `X-Total-Count` (the API now returns it).
- Empty states use `.empty` + `.e-ico` + one primary CTA.

### U-E · Guard rails (so this cannot come back)
- `ui_audit.mjs`: fail when `document.body.innerText` matches raw-key patterns (`\bcommon\.[a-zA-Z]`,
  `\bnav\.[a-zA-Z]`, `NAV\.[A-Z]`) or when any `.card` has a direct child heading with zero padding.
- Keep screenshot artifacts in CI and add the overview page to the sweep's "must have data" assertion
  once the seed runs in the e2e job.

## Order
```
U-A (i18n)  →  U-B (shell)  →  U-C (overview)  →  U-D (sweep)  →  U-E (guards)
```
Each step verified by: typecheck + build + 52-config sweep + my own screenshot read of the 5 main pages.

## Definition of done
No raw keys in any rendered page · every card uses header/body padding · KPI band has 4 real metrics ·
dates formatted consistently · EN/AR both correct · sweep and CI green · screenshots attached for review.

## Log

**2026-10-24 — U-A…U-D shipped.**
- **U-A**: `locale.ts` now imports `locales/en.json` / `locales/ar.json` statically; `loadMessages`, the
  runtime `fetch`, `deepMerge` and the duplicate `public/locales/` are gone. Raw keys (`common.appName`,
  `nav.home`, `NAV.GROUPCOMMAND`) no longer appear in the built app. 4 new tests incl. EN/AR key parity.
- **U-B**: new `PageHeader.vue` + `DcCard.vue`; eight pages converted to the card contract
  (`card-header` + `card-body`), so content finally has padding and headings sit in the header bar.
- **U-C**: overview rebuilt — 4-tile KPI band (datasets, certified metrics, open decisions, open alerts),
  two-column Next-actions checklist + Recent activity with `formatDateTime` and a new `formatRelative`.
- **U-D**: sidebar brand collision fixed; `/metrics` no longer dumps raw JSON (chips, per-rule eligibility,
  numerator/denominator sentences, raw JSON behind a lazy `Raw definition` disclosure); empty Dimensions
  box replaced with an honest hint; disabled Run-query explains itself; Pilot Setup moved next to Pilot Center.
- **U-E**: the sweep now fails on raw i18n keys, and its `null` check ignores predicate prose
  ("is not null"), which was a false positive.
Verified: 17 frontend tests, typecheck 0, build clean, **52/52 sweep FAILURES: 0** in EN and AR.
