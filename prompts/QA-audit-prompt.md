You are an independent 3rd-party QA auditor conducting a **zero-knowledge, comprehensive audit** of the **DecisionOS** project at `C:\Users\AMD\Desktop\DecisionOS`.

Your goal is to find EVERY problem — not just bugs, but design issues, UX gaps, security holes, dead ends, edge cases, test weaknesses, code quality problems, performance traps, and spec compliance failures.

---

## 1. AUDIT SCOPE & METHODOLOGY

Run ALL the following audits in order. Document every finding with: severity (Critical/High/Medium/Low), exact location (file:line), evidence (screenshot, log, stack trace), and recommendation.

---

## 2. UNIT TEST INTEGRITY

### 2.1 Run the full test suite
```bash
cd /c/Users/AMD/Desktop/DecisionOS/services/analytics && PYTHONPATH="" .venv/Scripts/python -m pytest tests/ --tb=long --basetemp=.ptmp -v 2>&1
```
- Are there ANY failures? Report each with full traceback.
- Are there flaky tests (pass sometimes, fail others)? Run 3x in a row.
- Check test coverage: `pip install coverage && PYTHONPATH="" .venv/Scripts/python -m coverage run -m pytest tests/ --basetemp=.ptmp && .venv/Scripts/python -m coverage report --show-missing`
- Are there untested code paths? Which modules have <80% coverage?
- Are there tests that pass but don't actually test anything (no assertions, or assertions that never fail)?

### 2.2 Test quality audit
For each test file, check:
- Do tests clean up after themselves? (temp files, DB state)
- Are there hardcoded paths that break on different machines?
- Do API tests verify response SHAPE (not just status code)?
- Are there tests for: auth rejection (wrong tenant/user), 404s, 422s?
- Are edge cases covered: empty data, null values, missing fields, max values, very long strings?

### 2.3 Code quality scan
- Run `ruff check .` or `pylint` on all Python files
- Check for: unused imports, unused variables, overly broad exception handlers (`except Exception` or bare `except:`)
- Are there mutable default arguments? (def fn(x=[])?)
- Is there commented-out dead code?
- Are there TODO/FIXME/HACK comments that signal known issues?
- Check type hints: are they accurate? Are `Any` used where a concrete type exists?

---

## 3. API AUDIT

### 3.1 Endpoint inventory
List ALL API endpoints by scanning `services/analytics/decisionos_analytics/api.py` for `@app.get`, `@app.post`, `@app.put`, `@app.delete`.

### 3.2 Smoke test every endpoint
Start the API in background:
```bash
cd /c/Users/AMD/Desktop/DecisionOS/services/analytics && PYTHONPATH="" .venv/Scripts/python -m uvicorn decisionos_analytics.api:create_app --factory --port 8100 --host 0.0.0.0 &
sleep 3
```
Then test EVERY endpoint with at least these scenarios:
- ✅ Happy path (valid data, expected 200/201)
- ❌ No auth headers (expect 401)
- ❌ Wrong tenant (expect 404 per spec §23.4 — no cross-tenant disclosure)
- ❌ Wrong user for tenant (expect 404)
- ❌ Invalid body (expect 422)
- ❌ Non-existent resource (expect 404)
- ❌ Malformed JSON (expect 422/400)
- ❌ Edge: empty body `{}`
- ❌ Edge: extra unknown fields (should be ignored or rejected?)

Document the response shape, status code, and any error messages for EVERY combination.

### 3.3 Specific endpoint attacks
- **Upload**: try uploading empty file, 100MB file, binary file (not CSV), CSV with mismatched columns, CSV with BOM, CSV with null bytes
- **Grain**: confirm grain after upload with non-existent dataset_id, confirm grain before any upload
- **Publish**: publish without grain confirmation, publish already-published revision, publish non-existent revision
- **Forecast**: train with 3 data points (spec says minimum 12), predict without training, predict with expired model_id
- **Monitoring**: evaluate with no rules defined, create rule with empty name, update non-existent rule, transition episode with invalid status
- **Bilingual search**: search with special characters, search with only whitespace, search with SQL injection patterns
- **Decisions**: create decision without required fields, transition from invalid current status
- **Scenarios/solve**: solve with infeasible constraints, solve with empty variables

---

## 4. FRONTEND & UI/UX AUDIT

### 4.1 Visual & navigation audit
Start the frontend:
```bash
cd /c/Users/AMD/Desktop/DecisionOS && node -v 2>/dev/null || (export PATH="/c/Users/AMD/AppData/Roaming/fnm/node-versions/latest:$PATH" && node -v)
```
If Nuxt can start, navigate to each page and check:
- All nav links work and go to the right place
- No broken images, missing CSS, JavaScript console errors
- Pages render without crashing on empty data
- Error states display user-friendly messages (not raw JSON or stack traces)
- Loading spinners/states work correctly
- Page titles and headings match
- The locale switcher (English/Arabic) works and RTL toggle functions
- Tab order works for keyboard navigation

### 4.2 Mobile/responsive check
- Does the layout break at 375px, 768px, 1024px widths?
- Are there horizontal scrollbars where they shouldn't be?
- Do buttons/links have adequate touch targets?

### 4.3 Accessibility check
- Are there proper `<label>` elements for form fields?
- Is there sufficient color contrast (4.5:1 for normal text)?
- Is keyboard navigation possible? Try tabbing through all interactive elements.
- Are there `aria-label` attributes on icon-only buttons?
- Are error messages announced in a way screen readers could detect?

---

## 5. SECURITY AUDIT

### 5.1 Information disclosure
- Do 404 responses confirm whether a resource exists vs. doesn't? Spec §23.4 says they MUST NOT.
- Do error messages expose internal details (file paths, SQL queries, stack traces)?
- Check that demo user ids don't leak other tenants' data

### 5.2 Input validation
- SQL injection: try `' OR 1=1 --` in dataset_id, metric_id, upload_id parameters
- Path traversal: try `../../etc/passwd` in filename
- XSS: try `<script>alert(1)</script>` in name/description fields
- Large payload: try POST with 10MB body

### 5.3 Authentication
- Are all endpoints behind `ctx()` or equivalent auth check?
- Check for any unprotected endpoints

---

## 6. DEAD END & EDGE CASE WALKTHROUGH

Simulate real user journeys and find dead ends:

1. **New user**: opens app, sees empty dashboards. Are there placeholder/onboarding messages or just blank pages?
2. **Upload → Parse → Grain → Publish → Metric**: follow the full path. Does the E2E test cover this? Can a user discover the next step?
3. **Delete/undo**: what happens when you upload the wrong file? Can you cancel? Is there a delete endpoint for datasets?
4. **Succession**: after forecasting, what's the obvious next action? After monitoring evaluation, can you drill into episodes?
5. **Error recovery**: if the API crashes mid-upload, can the user retry? Is idempotency working?
6. **Empty states**: every list page (datasets, rules, episodes, decisions) — what does it look like with zero items?

---

## 7. DATA INTEGRITY

### 7.1 SQLite store
- Open `services/analytics/dev.db` or the test DB. Check:
  - Are foreign keys enforced? (PRAGMA foreign_keys = ON is set)
  - Are there orphaned rows? (e.g., dataset_revision without dataset)
  - Do timestamps have consistent timezone? (all Z or all +00:00)
  - Are UUIDs truly unique?

### 7.2 Parquet data integrity
- After upload → publish: read the parquet file and compare row count with manifest
- Are there duplicate rows that shouldn't exist?
- Are null values preserved correctly?

---

## 8. CODE ARCHITECTURE REVIEW

### 8.1 Module coupling
- Does `monitoring.py` import from `store.py` directly or via the API layer?
- Is there circular import risk?
- Are `from .module import *` or lazy imports in `__init__.py` hiding dependencies?

### 8.2 Error handling
- Are all HTTP handlers wrapped in try/except for known exception types?
- Are there unhandled exceptions that would return 500?
- Is the audit trail (store.audit) called on every mutating action?

### 8.3 Duplication
- Is there copy-pasted code across modules?
- Are DDL statements duplicated? (monitoring tables created in both store.py SCHEMA and api.py evaluatescript)
- Is the same logic implemented differently in different places?

---

## 9. DOCUMENTATION GAPS

- Is the README accurate and complete?
- Do docstrings exist on all public functions?
- Are there inline comments explaining WHY (not just WHAT)?
- Would a new developer be able to run the project from scratch using only the documentation?

---

## 10. DELIVERABLE

Produce a single **QA Audit Report** with these sections:

```
# DecisionOS — 3rd Party QA Audit Report

## Executive Summary
{high-level findings count, severity breakdown, overall verdict}

## Critical/High Findings
{for each: severity, location, description, reproduction steps, impact, recommendation}

## Medium Findings
{for each: severity, location, description, impact, recommendation}

## Low/Observation Findings
{for each: severity, location, description, recommendation}

## Test Coverage Report
{coverage percentage by module, untested paths}

## API Surface Verification
{for each endpoint: methods, happy path, error paths, auth requirements}

## Dead Ends Identified
{list of user journey dead ends with suggested fixes}

## Security Notes
{vulnerabilities found, input validation gaps, disclosure issues}

## Code Quality Summary
{lint issues, duplication metrics, type hint coverage}

## Recommendation Priority List
{ordered from most to least critical}
```

---

## CONSTRAINTS
- Stay within `C:\Users\AMD\Desktop\DecisionOS`
- Do NOT modify any files unless explicitly fixing a CRITICAL issue
- For each finding, include exact reproduction steps so another developer can verify
- If a test or endpoint requires setup (upload, grain confirm, publish), include the setup steps
- Rate findings honestly — not everything is a "Critical" bug
- Do NOT connect to external services or download tools without reporting
- Spend maximum 60 minutes on this audit, prioritize the high-impact areas