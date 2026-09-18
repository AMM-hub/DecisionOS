You are building M4.3 — Simulation Worker for DecisionOS at C:\Users\AMD\Desktop\DecisionOS.

## SPEC REFERENCE (§17.5 — Discrete-event simulation)

The simulation must model: opening backlog with age/remaining service, time-varying arrivals, operating calendars, case classes, service distributions, qualification requirements, queue discipline, priority, shared staff, breaks, absences, transfers, rework routing, intake blocking, WIP limits, cancellations, competing exits, unfinished cases at horizon, terminal backlog, and outstanding age distribution.

Report completed and censored/unfinished populations separately. Validate conservation, zero-arrival behavior, unlimited-capacity behavior.

## CURRENT STATE
- Python analytics on :8100 with FastAPI, polars, pydantic, uvicorn, SQLite store
- SimPy 4.1 is already installed in the venv at `services/analytics/.venv/`
- Decision register (spec §19) is done with CRUD API at /v1/decisions/
- Scenario optimization engine (spec §17.3) done at /v1/scenarios/solve
- 89 tests passing overall

## YOUR TASK

Create `services/analytics/decisionos_analytics/simulation.py` with:

### 1. Core simulation engine using SimPy
- A `SimulationModel` class that configures: number of staff, service time distribution (mean + std), arrival rate (cases per period), queue disciplines (FIFO, priority), opening backlog, and simulation horizon.
- `run_simulation(config)` function that runs the DES and returns results.

### 2. Results model
Simple dataclass with: total_completed, total_censored (unfinished at horizon), average_wait_time, max_wait_time, terminal_backlog, average_backlog, time_series snapshots (backlog over time).

### 3. Validation fixtures
- `simple_queue_fixture()` — a 2-server queue with known arrival/service rates. Known outcome: with 10 servers, 8 cases/hour arrivals, 1h mean service, M/M/c approximation predicts ~4h wait max.
- Test that backlog can't exceed total arrivals + opening (conservation).
- Test zero-arrival behavior (backlog drains monotonically).
- Test unlimited-capacity behavior (no queue forms when servers >> arrival rate).

### 4. API endpoints
Add to `api.py` (before `app.state.store = store`):
- `POST /v1/simulations/run` — accepts a JSON config, runs the simulation, returns results. Uses tenant/auth from headers.

### 5. Tests
Create `tests/test_simulation.py` with:
- Unit test for simple_queue_fixture (completes within horizon, backlog conserves)
- Unit test for zero-arrivals (backlog drains)
- Unit test for unlimited-capacity (zero wait)
- API integration test via TestClient

## IMPORTANT CONSTRAINTS
- PYTHONPATH must be cleared when running: `PYTHONPATH="" .venv/Scripts/python -m pytest ...`
- Use TMPDIR=/c/Users/AMD/Desktop/DecisionOS/services/analytics/.tmp for pytest temp files (Windows permission issue)
- SimPy is installed in: services/analytics/.venv/Lib/site-packages/
- Don't modify any existing tests or modules (just add new ones)
- Follow the same patterns as existing modules (workflow.py, optimization.py, register.py)

## VERIFICATION
After creating all files, run:
```bash
cd /c/Users/AMD/Desktop/DecisionOS/services/analytics
TMPDIR=/c/Users/AMD/Desktop/DecisionOS/services/analytics/.tmp PYTHONPATH="" .venv/Scripts/python -m pytest tests/test_simulation.py -v
```
All tests must pass.