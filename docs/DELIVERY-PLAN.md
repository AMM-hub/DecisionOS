# Delivery Plan — DecisionOS

**Owner:** Autonomous build via OpenCode Go (Qwen3.8 Flash)
**Spec:** `DecisionOS_Master_Business_and_Technical_Specification.md` (35 sections, 2035 lines)
**Started:** 16 September 2026

## Dependency Graph

```
M1 ────────────────────────────────────── Core pipeline (DONE)
 │                                          │
 ├──→ M2 ─── Forecasting Lab               │
 │        ├── StatsForecast integration     │
 │        ├── Time-series API endpoints     │
 │        └── Forecast frontend             │
 │                                          │
 ├──→ M3 ─── Workflow Analytics            │
 │        ├── Event store schema            │
 │        ├── Process mining (PM4Py)        │
 │        └── Workflow dashboards           │
 │                                          │
 ├──→ M4 ─── Scenario & Decision Studio    │
 │        ├── Optimization/simulation       │
 │        ├── Scenario API + frontend       │
 │        └── Decision register             │
 │                                          │
 ├──→ M5 ─── Monitoring & Alerts           │
 │        ├── Alert rules engine            │
 │        ├── Contextual monitoring         │
 │        └── Alert frontend                │
 │                                          │
 └──→ M6 ─── Arabic/English Bilingual       │
          ├── Vue I18n setup               │
          ├── RTL layout                   │
          └── Bilingual dashboards         │
                                           │
                M7 ─── Final Polish ───────┘
                     QA, docs, performance
```

## Milestone Breakdown

### M1 — Core Pipeline + Frontend ✅ DONE
- Python analytics: 25 tests passing, 23+ API endpoints, E2E verified
- Nuxt frontend: 4 pages (dashboard, uploads, datasets, metrics), API composable, full types
- Laravel API: 13.32 on SQLite fallback, 19 routes
- CORS, new endpoints (/health, /uploads, /schema, withdraw)

**Verification:** 25/25 tests pass, E2E demo 10/10 steps pass, all 3 services live

---

### M2 — Forecasting Lab (SPEC §16)
**Goal:** Add time-series forecasting with honest uncertainty intervals

| Deliverable | Description | Depends On |
|-------------|-------------|-----------|
| M2.1 | StatsForecast integration in Python analytics | M1 Python API |
| M2.2 | Forecast API endpoints (train, predict, evaluate) | M2.1 |
| M2.3 | Forecast frontend component (Nuxt page) | M2.2 |
| M2.4 | Forecast evaluation + accuracy monitoring | M2.1, M2.3 |

**Verification Gates:**
- G2.1: StatsForecast installs and imports in analytics venv
- G2.2: `/v1/forecasts/train` accepts dataset + metric + horizon, returns model spec
- G2.3: `/v1/forecasts/predict` returns prediction intervals, not point estimates
- G2.4: Forecast component renders chart with uncertainty bands
- G2.5: Holdout evaluation compares models; refuses when data insufficient

---

### M3 — Workflow Analytics (SPEC §15)
**Goal:** Event-sourced process mining with bottleneck detection

| Deliverable | Description | Depends On |
|-------------|-------------|-----------|
| M3.1 | Event store PostgreSQL schema + SQLite equivalent | M1 |
| M3.2 | PM4Py process mining integration | M3.1 |
| M3.3 | Workflow analytics API endpoints | M3.2 |
| M3.4 | Workflow frontend (Sankey, funnel, transition charts) | M3.3 |

**Verification Gates:**
- G3.1: Case events parsed and stored with correct ordering
- G3.2: Bottleneck detection identifies stages with longest wait times
- G3.3: Variant analysis groups similar process paths
- G3.4: Conformance checking compares actual vs expected flows
- G3.5: Workflow dashboard renders process map

---

### M4 — Scenario & Decision Studio (SPEC §17-19)
**Goal:** What-if analysis, optimization, simulation, and decision register

| Deliverable | Description | Depends On |
|-------------|-------------|-----------|
| M4.1 | Optimization engine (PuLP/HiGHS) integration | M1 |
| M4.2 | Scenario templates + API | M4.1 |
| M4.3 | Simulation worker (SimPy) | M4.2 |
| M4.4 | Decision register CRUD + immutable audit | M1 |
| M4.5 | Scenario + Decision frontend pages | M4.3, M4.4 |

**Verification Gates:**
- G4.1: Optimization solver returns feasible/optimal/infeasible correctly
- G4.2: Scenario comparison shows multiple options with trade-offs
- G4.3: Decision records create immutable audit trail
- G4.4: Decision outcomes link back to original evidence
- G4.5: Frontend renders scenario comparison table + decision timeline

---

### M5 — Monitoring & Alerts (SPEC §14)
**Goal:** Contextual monitoring with data health and business alerts

| Deliverable | Description | Depends On |
|-------------|-------------|-----------|
| M5.1 | Alert rule engine + condition evaluation | M1 |
| M5.2 | Data health incident detection | M1 |
| M5.3 | Alert delivery (in-app + webhook) | M5.1 |
| M5.4 | Monitoring dashboard frontend | M5.3 |

**Verification Gates:**
- G5.1: Alert rule can be created from metric + threshold
- G5.2: Threshold breach triggers alert episode with context
- G5.3: Data freshness incident fires when source stops updating
- G5.4: Alert deduplication prevents notification storms
- G5.5: Monitoring page shows active/acknowledged/resolved alerts

---

### M6 — Arabic/English Bilingual (SPEC §27)
**Goal:** Full bilingual support with RTL layout

| Deliverable | Description | Depends On |
|-------------|-------------|-----------|
| M6.1 | Vue I18n configuration with ICU format | M1 frontend |
| M6.2 | RTL CSS foundation + layout switch | M6.1 |
| M6.3 | Arabic translations (all UI strings) | M6.1 |
| M6.4 | Bilingual dashboard rendering | M6.2, M6.3 |

**Verification Gates:**
- G6.1: Language switch works without page reload
- G6.2: RTL layout renders correctly (nav, cards, tables, charts)
- G6.3: All UI strings translated to Arabic
- G6.4: Date/currency formats respect locale (BHD, Hijri calendar options)

---

### M7 — Final Integration & QA
**Goal:** Polish, docs, complete spec coverage

| Deliverable | Description | Depends On |
|-------------|-------------|-----------|
| M7.1 | Complete QA acceptance matrix (QA-001 through QA-060) | All |
| M7.2 | Performance optimization | All |
| M7.3 | Project documentation | All |
| M7.4 | Final E2E verification across all modules | All |

**Verification Gates:**
- G7.1: All acceptance tests pass
- G7.2: E2E scenario covers entire decision lifecycle
- G7.3: README + docs updated
- G7.4: No known critical defects

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Python library compatibility | StatsForecast/PuLP versions conflict with Python 3.14 | Med | Pin compatible versions, test imports first |
| Forecasting quality on small data | Models overfit or refuse on 420 rows | High | Implement refusal protocol early (spec §16.4) |
| Solver licensing | HiGHS binaries on Windows | Med | Use PuLP + HiGHS bundled; test solver availability |
| i18n performance | RTL + bilingual JSON key overhead | Low | Lazy-load translations, test bundle size |
| Scope creep on AI gateway | Building full gateway delays other modules | Low | Use simple OpenAI-format abstraction; defer advanced routing |
| Docker dependency | Can't run PostgreSQL for full integration tests | High | Use SQLite equivalents throughout; Docker is deployment-only |

## Execution Approach

Each milestone is executed via:
1. Write prompt file with spec excerpts + task instructions
2. Run `opencode run -m opencode-go/qwen3.8-flash -f <prompt> -- "task"`
3. Verify with tests + curl after completion
4. Commit progress
5. Move to next milestone