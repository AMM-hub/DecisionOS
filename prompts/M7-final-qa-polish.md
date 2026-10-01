You are running M7 — Final QA & Polish for **DecisionOS** at C:\Users\AMD\Desktop\DecisionOS.

## OBJECTIVE
Run a comprehensive final quality pass: fix any test failures, ensure all API endpoints work, clean up edge cases, verify consistency across the frontend pages, and add any missing coverage.

## CURRENT STATE
- **173 tests passing** (all M1-M6)
- Python analytics API on :8100
- Nuxt frontend on :3000
- Markdown spec at DecisionOS_Master_Business_and_Technical_Specification.md (2035 lines)

## YOUR TASKS

### 1. RUN FULL TEST SUITE
```bash
cd /c/Users/AMD/Desktop/DecisionOS/services/analytics
PYTHONPATH="" .venv/Scripts/python -m pytest tests/ --tb=long --basetemp=.ptmp -v 2>&1
```
Fix any failures you find.

### 2. VERIFY ALL API ENDPOINTS WORK
Using TestClient or curl against the Python API, verify these endpoints return 200/201:
- GET /v1/health
- GET /v1/datasets
- GET /v1/monitoring/health
- GET /v1/monitoring/rules
- GET /v1/monitoring/conditions
- GET /v1/monitoring/episodes
- GET /v1/bilingual/labels
- POST /v1/bilingual/search
- POST /v1/monitoring/rules (then GET to verify)
- POST /v1/forecasts/suitability (requires dataset)
- POST /v1/scenarios/solve (requires scenario data)

### 3. FRONTEND CONSISTENCY
- All 7 nav pages (Overview, Uploads, Datasets, Metrics, Forecasts, Workflow, Scenarios, Monitoring) link correctly.
- locale switcher works and persists.
- RTL mode toggles correctly.

### 4. EDGE CASE COVERAGE
- Empty datasets / no-data states in monitoring pages
- Invalid locale codes fall back gracefully
- Search with empty query returns all
- Search with non-existent query returns empty
- Monitoring with zero rules evaluates gracefully

### 5. FIX WARNINGS
Address the 542 deprecation warnings if practical (mostly PuLP/Starlette).
At minimum: fix the `lxml` import issue that PM4Py has.

### 6. FINAL VERIFICATION
```bash
cd /c/Users/AMD/Desktop/DecisionOS/services/analytics
PYTHONPATH="" .venv/Scripts/python -m pytest tests/ --tb=short --basetemp=.ptmp —tb=short -q 2>&1
```
All tests must pass. Commit with message: "M7 Final QA & Polish — complete"

## CONSTRAINTS
- Stay ONLY under C:\Users\AMD\Desktop\DecisionOS
- Do not break existing functionality
- All 173+ existing tests must continue to pass