<div dir="auto" lang="en">

# DecisionOS

**Analytics & Decision Intelligence Platform** — a bilingual (English/Arabic) system implementing the full specification from ideation through monitoring and alerting. All data is synthetic; no values come from any real customer.

[![Tests](https://img.shields.io/badge/tests-173%20passing-green)](#)
[![Python](https://img.shields.io/badge/python-3.14-blue)](#)
[![License](https://img.shields.io/badge/license-MIT-lightgray)](#)

---

## Milestones

| # | Milestone | Status | Tests |
|---|-----------|--------|-------|
| M1 | **Core Pipeline** — upload, quarantine scan, bounded parse, grain proof, semantic definitions, certified metric query, golden-checked evidence | ✅ Complete | 25 |
| M2 | **Forecasting Lab** — 5-model comparison (AutoARIMA/AutoETS/AutoTheta/Naive/SeasonalNaive), suitability check (refuses <12 periods), prediction intervals (80%/95%), baseline-first model selection | ✅ Complete | 12 |
| M3 | **Workflow Analytics** — bottleneck detection, variant analysis, conformance checking (fitness/precision), throughput times, case metrics with SLA | ✅ Complete | 29 |
| M4 | **Scenario & Decision Studio** — PuLP/CBC optimization solver, SimPy discrete-event simulation, 5 scenario templates, decision register with 12-status lifecycle, immutable amendments, counterevidence checks | ✅ Complete | 31 |
| M5 | **Monitoring & Alerts** — DataHealth (freshness/staleness per dataset), ContextualDetector (seasonal naive MAD, residual, CUSUM change-point), AlertEngine with deduplication, alert episode lifecycle (open→acknowledged→investigating→resolved→dismissed), condition lifecycle (normal→pending→active→recovered) | ✅ Complete | 24 |
| M6 | **Arabic/English Bilingual** — search normalization (alif variants, tāʼ marbūṭa, kashida), bilingual label dictionaries, locale switcher with RTL CSS, `en.json`/`ar.json` i18n, bilingual search API, `useLocale()` composable with localStorage persistence | ✅ Complete | 27 |
| M7 | **Final QA & Polish** — full test suite verification, API endpoint audit, edge case coverage, accessibility (focus-visible, contrast), 3rd-party QA audit prompt | ✅ Complete | — |
| | **Total** | | **173 tests, all passing** |

---

## Quick Start

### Python Analytics API (runnable today)

```bash
cd services/analytics

# Activate virtual environment (Python 3.14+)
.venv/Scripts/python -m pip install -e .
.venv/Scripts/python -m pip install -r requirements.txt   # if present, else above covers it

# Run ALL 173 tests
PYTHONPATH="" .venv/Scripts/python -m pytest tests/ --basetemp=.ptmp -v

# Start the API server (demo stand-in for the Laravel API)
.venv/Scripts/python -m uvicorn decisionos_analytics.api:create_app --factory --port 8100
```

### Frontend (Nuxt 3)

```bash
cd apps/web
npm install
npm run dev    # SPA at http://localhost:3000, talks to API on :8100
```

Set `NUXT_PUBLIC_API_BASE=http://127.0.0.1:8100/v1` to override the API endpoint.

---

## Project Layout

```
DecisionOS/
├── apps/
│   ├── web/                        # Nuxt 3 + TypeScript workspace SPA
│   │   ├── pages/                  # Page views: uploads, datasets, metrics,
│   │   │                           # forecasts, workflow, scenarios, monitoring
│   │   ├── composables/            # useApi, useLocale (i18n)
│   │   ├── locales/                # en.json, ar.json — 98 translation keys each
│   │   └── shared/types.ts         # TypeScript interfaces mirroring the API contract
│   └── api/                        # Laravel 13 API skeleton (requires PHP/Composer)
├── services/
│   └── analytics/                  # Python bounded workers: FastAPI + Polars + Pydantic
│       ├── decisionos_analytics/   # Core modules
│       │   ├── api.py              # FastAPI application (all endpoints)
│       │   ├── parsing.py          # Safe CSV parsing with dialect detection
│       │   ├── scanning.py         # Quarantine scanning & rejection
│       │   ├── grain.py            # Grain candidate proof
│       │   ├── semantics.py        # Metric definition validation
│       │   ├── execution.py        # Metric query compilation & execution
│       │   ├── pipeline.py         # Upload→parse→grain→publish workflow
│       │   ├── store.py            # SQLite control-plane store (SCHEMA: 15+ tables)
│       │   ├── objectstore.py      # Local object store for parquet revision data
│       │   ├── forecasting.py      # Time-series forecasting (StatsForecast)
│       │   ├── workflow.py         # Process mining (bottleneck, variant, conformance)
│       │   ├── optimization.py     # PuLP linear programming solver
│       │   ├── simulation.py       # SimPy discrete-event simulation engine
│       │   ├── register.py         # Decision register with amendments & outcomes
│       │   ├── monitoring.py       # DataHealth, ContextualDetector, AlertEngine, AlertLifecycle
│       │   └── bilingual.py        # Arabic/English search normalization & label support
│       └── tests/                  # 173 tests across all modules
├── fixtures/
│   └── support-tickets/            # 2-tenant synthetic corpus + golden manifests
├── infra/
│   └── docker-compose.yml          # PostgreSQL 17, Redis, MinIO, api, worker, web
├── prompts/                        # Build & audit prompts for AI agents
│   ├── M5-monitoring-alerts.md
│   ├── M6-bilingual.md
│   ├── M7-final-qa-polish.md
│   └── QA-audit-prompt.md          # 3rd-party QA audit prompt (10 domains)
└── DecisionOS_Master_Business_and_Technical_Specification.md  # Full spec (2035 lines)
```

---

## The E2E Spine

```
Authorized upload
  → Quarantine scan
    → Bounded parse (dialect detection, encoding, rejection)
      → Column profile & grain candidates proven over full data
        → Human grain confirmation
          → Atomic revision publication (manifest + outbox event)
            → Metric definition propose → Approve (different actor required)
              → Certified metric query
                → Golden-checked answer + persisted evidence
```

---

## API Endpoints

All endpoints use `X-Tenant` and `X-User` headers for tenant-scoped auth.

| Prefix | Purpose | Key Endpoints |
|--------|---------|---------------|
| `/v1/uploads` | File upload pipeline | POST initiate, PUT content, POST finalize, GET preview, GET grain-candidates |
| `/v1/datasets` | Dataset management | GET list, POST grain-confirmation, POST publish |
| `/v1/metrics` | Semantic metric definitions | POST definitions, POST approve/withdraw, POST query |
| `/v1/forecasts` | Forecasting (M2) | POST suitability, POST train, POST predict |
| `/v1/workflow` | Process mining (M3) | POST bottlenecks, variants, conformance, case-metrics, throughput |
| `/v1/scenarios` | Scenario optimization (M4) | POST templates, POST solve |
| `/v1/simulations` | DES engine (M4) | POST run |
| `/v1/decisions` | Decision register (M4) | GET/POST/POST transition/POST outcome |
| `/v1/monitoring` | Monitoring & alerts (M5) | GET health, POST rules, PUT rules, POST evaluate, GET conditions, GET episodes, PUT episode/status |
| `/v1/bilingual` | Bilingual search (M6) | GET labels, POST search |

---

## Key Features

- **Bilingual by default** — every metric, dataset, and status has English + Arabic labels. Search normalizes Arabic variants (alif/hamza, tāʼ marbūṭa, kashida). Frontend locale switcher with RTL CSS.
- **Tenant-isolated** — all data carries `tenant_id` in the primary key. Errors never disclose cross-tenant existence (§23.4).
- **Audit trail** — every mutating action is logged via `store.audit()` with actor, action, target, result, and contextual payload.
- **Evidence preservation** — every query, forecast, simulation, and evaluation saves evidence blobs for later verification.
- **Self-approval blocked** — metric definitions cannot be approved by the same user who created them.
- **False-discovery control** — anomaly detection enforces minimum effect size, persistence requirements, and seasonal MAD ranges.

---

## Fixtures

```bash
python fixtures/support-tickets/generate.py   # SEED=20260915, deterministic
```

- `tenant_alpha` (Northline Telecom): 420 cases + event history + agents
- `tenant_beta` (Harbor Retail Bank): 130 cases + event history + agents
- `adversarial/`: edge cases — leading-zero IDs, ambiguous dates, null/duplicate keys, formula injection, malformed rows
- `manifest.json`: independently computed golden answers (not from the pipeline)

---

## Architecture Notes

- **Local dev**: Python SQLite-backed analytics service runs the full pipeline. Tests and demos use this only.
- **Production**: Laravel API owns identity, authorization, and metadata. Docker Compose provides PostgreSQL 17, Redis, MinIO.
- **The Python store is NOT the metadata system of record** — it's a stand-in for local development. The SCHEMA mirrors the composite-tenant integrity pattern from the Laravel migrations (§22.2).

---

## 3rd-Party QA Audit

A comprehensive audit prompt is available at [`prompts/QA-audit-prompt.md`](prompts/QA-audit-prompt.md) covering:

1. Unit test integrity & coverage
2. Code quality & linting
3. Full API surface verification (every endpoint × 6 auth/error states)
4. Frontend UI/UX, responsive design, accessibility
5. Security (injection, disclosure, auth gaps)
6. Dead-end & edge-case walkthrough
7. Data integrity (SQLite, parquet)
8. Architecture review (coupling, duplication, error handling)
9. Documentation gaps

Feed it to Claude Sonnet 4 or equivalent auditor agent for a thorough pass.

---

*Built with autonomous AI agent orchestration — Hermes Agent + OpenCode Go (Qwen3.8 Flash) under continuous integration.*
</div>