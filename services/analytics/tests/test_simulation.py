"""M4.3 Simulation Worker tests (spec §17.5 — discrete-event simulation).

Validation guarantees verified here:
1. Conservation: completed + censored == opening backlog + arrivals.
2. Zero-arrival behavior: backlog drains monotonically.
3. Unlimited-capacity behavior: no queue forms, zero wait.
4. Fixture with known outcome envelope (10 servers, 8/hr arrivals, 1h service).
5. API integration for POST /v1/simulations/run.
"""

from __future__ import annotations

import pytest

from decisionos_analytics.simulation import (
    SimulationConfig,
    SimulationError,
    run_simulation,
    simple_queue_fixture,
    unlimited_capacity_fixture,
    zero_arrival_fixture,
)


# ---------------------------------------------------------------------------
# fixture with known outcome
# ---------------------------------------------------------------------------


def test_simple_queue_fixture_completes_within_horizon():
    cfg, expected = simple_queue_fixture()
    r = run_simulation(cfg)
    assert r.total_completed >= expected["min_completed"]
    assert r.max_wait_time < expected["max_wait_time_upper"]
    assert r.horizon == cfg.horizon


def test_simple_queue_fixture_conserves_population():
    cfg, _ = simple_queue_fixture()
    r = run_simulation(cfg)
    assert r.total_completed + r.total_censored == r.opening_backlog + r.total_arrived


def test_backlog_never_exceeds_opening_plus_arrivals():
    """Conservation over time: no snapshot may exceed total work ever present."""
    cfg, _ = simple_queue_fixture()
    r = run_simulation(cfg)
    cap = r.opening_backlog + r.total_arrived
    assert max(s["backlog"] for s in r.time_series) <= cap


# ---------------------------------------------------------------------------
# zero-arrival behavior (§17.5 validation)
# ---------------------------------------------------------------------------


def test_zero_arrivals_backlog_drains_monotonically():
    cfg, expected = zero_arrival_fixture()
    r = run_simulation(cfg)
    assert r.total_arrived == expected["arrivals"]
    assert r.total_completed == expected["completed"]
    assert r.total_censored == expected["censored"]
    series = [s["backlog"] for s in r.time_series]
    assert series == sorted(series, reverse=True), f"backlog not monotonic: {series}"
    assert series[0] == cfg.opening_backlog
    assert series[-1] == 0


def test_zero_arrivals_censored_when_horizon_too_short():
    cfg = SimulationConfig(num_servers=1, service_mean=2.0, service_std=0.0,
                           arrival_rate=0.0, opening_backlog=10, horizon=5.0,
                           snapshot_interval=1.0, seed=3)
    r = run_simulation(cfg)
    assert r.total_completed == 2
    assert r.total_censored == 8
    assert r.terminal_backlog == 8
    assert r.total_completed + r.total_censored == 10


# ---------------------------------------------------------------------------
# unlimited-capacity behavior (§17.5 validation)
# ---------------------------------------------------------------------------


def test_unlimited_capacity_zero_wait():
    cfg, expected = unlimited_capacity_fixture()
    r = run_simulation(cfg)
    assert r.max_wait_time == expected["max_wait_time"]
    assert r.average_wait_time == 0.0
    assert r.server_utilization <= expected["utilization_max"]
    assert r.total_completed + r.total_censored == r.total_arrived


# ---------------------------------------------------------------------------
# queue disciplines & config
# ---------------------------------------------------------------------------


def test_priority_discipline_runs_and_conserves():
    cfg = SimulationConfig(num_servers=3, arrival_rate=10.0, service_mean=1.0,
                           service_std=1.0, queue_discipline="priority",
                           horizon=50.0, seed=1)
    r = run_simulation(cfg)
    assert r.total_completed + r.total_censored == r.total_arrived
    assert r.outstanding_ages["count"] == float(r.total_censored)


def test_time_varying_arrivals_respect_schedule():
    cfg = SimulationConfig.from_dict({
        "num_servers": 5, "service_mean": 1.0, "service_std": 0.0,
        "arrival_rate": 0.0,
        "arrival_schedule": [{"from_t": 0, "rate": 0.0}, {"from_t": 10, "rate": 4.0}],
        "horizon": 20.0, "snapshot_interval": 1.0, "seed": 5,
    })
    r = run_simulation(cfg)
    # no arrivals in first 10 hours
    assert all(s["backlog"] == 0 for s in r.time_series if s["t"] <= 10)
    # ~40 arrivals expected in 10..20; all but in-flight complete by horizon
    assert 25 <= r.total_arrived <= 60
    assert r.total_completed + r.total_censored == r.total_arrived


def test_seed_makes_run_deterministic():
    cfg, _ = simple_queue_fixture()
    a = run_simulation(cfg)
    b = run_simulation(cfg)
    assert a.total_completed == b.total_completed
    assert a.max_wait_time == b.max_wait_time
    assert a.time_series == b.time_series


def test_invalid_config_rejected():
    with pytest.raises(SimulationError):
        SimulationConfig(num_servers=0).validate()
    with pytest.raises(SimulationError):
        SimulationConfig(service_mean=-1).validate()
    with pytest.raises(SimulationError):
        SimulationConfig(queue_discipline="sjf").validate()
    with pytest.raises(SimulationError):
        SimulationConfig.from_dict({"arrival_rate": -3})


# ---------------------------------------------------------------------------
# API integration
# ---------------------------------------------------------------------------


def test_simulation_run_endpoint(client, alpha_headers):
    body = {
        "num_servers": 10,
        "arrival_rate": 8.0,
        "service_mean": 1.0,
        "service_std": 1.0,
        "opening_backlog": 5,
        "horizon": 200.0,
        "snapshot_interval": 5.0,
        "seed": 42,
    }
    r = client.post("/v1/simulations/run", json=body, headers=alpha_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "answered"
    assert data["total_completed"] + data["total_censored"] == data["opening_backlog"] + data["total_arrived"]
    assert data["max_wait_time"] < 4.0
    assert 38 <= len(data["time_series"]) <= 40  # ~horizon/snapshot_interval (final sample may land exactly at cutoff)
    assert data["evidence_ref"]


def test_simulation_run_endpoint_requires_auth(client):
    r = client.post("/v1/simulations/run", json={"num_servers": 2})
    assert r.status_code == 401


def test_simulation_run_endpoint_rejects_invalid_config(client, alpha_headers):
    r = client.post("/v1/simulations/run", json={"num_servers": 0}, headers=alpha_headers)
    assert r.status_code == 422
    assert r.json()["detail"].startswith('{"code": "invalid_simulation_config"')


def test_simulation_run_endpoint_tenant_isolation(client, alpha_headers, beta_headers):
    body = {"num_servers": 2, "arrival_rate": 1.0, "horizon": 10.0, "snapshot_interval": 1.0}
    ra = client.post("/v1/simulations/run", json=body, headers=alpha_headers)
    rb = client.post("/v1/simulations/run", json=body, headers=beta_headers)
    assert ra.status_code == 200 and rb.status_code == 200
    # evidence refs must differ per tenant and both runs are independent
    assert ra.json()["evidence_ref"] != rb.json()["evidence_ref"]
    assert ra.json()["total_completed"] == rb.json()["total_completed"]  # same seed
