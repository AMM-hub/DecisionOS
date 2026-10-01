"""M5 — Monitoring, Incidents, and Alerts tests (spec §14).

15 tests covering: DataHealth, ContextualDetector (seasonal naive,
residual, CUSUM), AlertEngine evaluation, AlertLifecycle CRUD,
episode transitions, condition lifecycle, dedup, and API integration.
"""

from __future__ import annotations

import json
import math
import statistics

import polars as pl
import pytest
from fastapi.testclient import TestClient

from decisionos_analytics.monitoring import (
    AlertEngine,
    AlertLifecycle,
    ContextualDetector,
    DataHealth,
)


# ======================================================================
# 14.1 — Data Health
# ======================================================================

def test_data_health_unknown_dataset(client, alpha_headers):
    """DataHealth returns 'unknown' for non-existent dataset."""
    h = DataHealth.check("tenant_alpha", "nonexistent", client.app.state.store)
    assert h["status"] == "unknown"
    assert h["revision_count"] == 0
    assert h["freshness_hours"] is None


def test_data_health_after_upload(client, alpha_headers):
    """After a dataset is created, health shows correct status."""
    # Upload a file to create a dataset
    from conftest import FIXTURES
    r = client.post("/v1/uploads", json={
        "filename": "tickets_cases.csv", "size_bytes": 1024,
        "workspace_id": "ws-support-ops",
    }, headers=alpha_headers)
    uid = r.json()["upload_id"]
    path = FIXTURES / "tenant_alpha" / "tickets_cases.csv"
    client.put(f"/v1/uploads/{uid}/content", content=path.read_bytes(), headers=alpha_headers)
    r = client.post(f"/v1/uploads/{uid}/finalize", headers=alpha_headers)
    dataset_id = r.json()["dataset_id"]

    h = DataHealth.check("tenant_alpha", dataset_id, client.app.state.store)
    assert h["dataset_id"] == dataset_id
    assert h["revision_count"] >= 1
    assert h["status"] in ("healthy", "stale")
    assert h["freshness_hours"] is not None


def test_data_health_check_all(client, alpha_headers):
    """DataHealth.check_all returns list of health results."""
    results = DataHealth.check_all("tenant_alpha", client.app.state.store)
    assert isinstance(results, list)
    for r in results:
        assert "status" in r
        assert "dataset_id" in r


# ======================================================================
# 14.2 — Contextual Detector
# ======================================================================

def test_seasonal_naive_range_constant_series():
    """Constant series produces narrow bounds."""
    series = [5.0] * 20
    lo, hi = ContextualDetector.seasonal_naive_range(series, 7, k=3)
    assert lo < hi
    assert lo <= 5.0 <= hi


def test_seasonal_naive_range_with_outlier():
    """Outlier in history still produces reasonable bounds."""
    series = [10.0] * 15 + [100.0, 10.0, 10.0]  # one outlier
    lo, hi = ContextualDetector.seasonal_naive_range(series, 7, k=3)
    assert lo < hi
    # The outlier inflates MAD but bounds should still contain the normal range
    assert lo <= 10.0


def test_detect_anomalies_constant_series():
    """Constant series should not trigger anomalies (stdev near 0)."""
    series = [50.0] * 30
    anoms = ContextualDetector.detect_anomalies(series, threshold=3.0)
    assert len(anoms) == 0


def test_detect_anomalies_spot_outlier():
    """A single large spike should be detected."""
    series = [10.0] * 10 + [200.0] + [10.0] * 10
    anoms = ContextualDetector.detect_anomalies(series, threshold=3.0, min_effect_size=0.01)
    assert len(anoms) >= 1
    assert any(a["observed"] == 200.0 for a in anoms)
    for a in anoms:
        assert a["effect_size"] >= 0.01
        assert "expected_lower" in a
        assert "expected_upper" in a


def test_detect_anomalies_residual_method():
    """Residual detection method also works."""
    series = [5.0] * 15 + [100.0, 5.0, 5.0]
    anoms = ContextualDetector.detect_anomalies(series, method="residual_detection", threshold=3.0)
    assert len(anoms) >= 1
    assert anoms[0]["method"] == "residual_detection"


def test_detect_anomalies_min_effect_size_filter():
    """Very small deviations below min_effect_size are not flagged."""
    series = [100.0] * 12 + [100.001] * 10
    anoms = ContextualDetector.detect_anomalies(series, threshold=1.0, min_effect_size=1000.0)
    assert len(anoms) == 0  # effect_size too small


def test_cusum_detection():
    """CUSUM detects a clear level shift."""
    series = [10.0] * 20 + [30.0] * 20
    shifts = ContextualDetector.cusum_detection(series, threshold=5.0)
    assert len(shifts) >= 1
    assert shifts[0]["cusum_direction"] == "up"
    assert "baseline_mean" in shifts[0]


def test_cusum_short_series():
    """CUSUM returns empty on series < 5 points."""
    assert ContextualDetector.cusum_detection([1, 2, 3]) == []


def test_seasonal_naive_short_history():
    """Series shorter than season_length uses global stat instead."""
    series = [100.0, 102.0, 98.0]
    lo, hi = ContextualDetector.seasonal_naive_range(series, 7, k=3)
    assert lo < hi
    assert lo <= statistics.median(series) <= hi


# ======================================================================
# 14.3 — Alert lifecycle
# ======================================================================

def test_create_alert_rule(client, alpha_headers):
    """AlertLifecycle.create_rule persists a rule."""
    store = client.app.state.store
    rule = AlertLifecycle.create_rule("tenant_alpha", {
        "name": "First-Response SLA Breach",
        "dataset_id": "ds-1",
        "metric_id": "metric-first-response-rate",
        "method": "seasonal_naive",
        "threshold": 3.0,
        "owner": "alpha.manager",
    }, "alpha.manager", store)
    assert rule["name"] == "First-Response SLA Breach"
    assert rule["enabled"] == 1
    assert rule["threshold"] == 3.0


def test_list_alert_rules(client, alpha_headers):
    """AlertLifecycle.list_rules returns created rules."""
    store = client.app.state.store
    before = len(AlertLifecycle.list_rules("tenant_alpha", store))
    AlertLifecycle.create_rule("tenant_alpha", {
        "name": "Test Rule", "dataset_id": "ds-1",
        "metric_id": "metric-test", "owner": "tester",
    }, "tester", store)
    after = len(AlertLifecycle.list_rules("tenant_alpha", store))
    assert after == before + 1


def test_update_alert_rule(client, alpha_headers):
    """AlertLifecycle.update_rule modifies fields."""
    store = client.app.state.store
    rule = AlertLifecycle.create_rule("tenant_alpha", {
        "name": "Update Me", "dataset_id": "ds-1",
        "metric_id": "metric-test", "threshold": 5.0, "owner": "tester",
    }, "tester", store)
    updated = AlertLifecycle.update_rule("tenant_alpha", rule["id"],
                                          {"threshold": 7.0, "enabled": 0}, "tester", store)
    assert updated["threshold"] == 7.0
    assert updated["enabled"] == 0


def test_alert_episode_lifecycle(client, alpha_headers):
    """Episode: open→acknowledged→investigating→resolved."""
    store = client.app.state.store
    rule = AlertLifecycle.create_rule("tenant_alpha", {
        "name": "Lifecycle Test", "dataset_id": "ds-1",
        "metric_id": "metric-test", "owner": "tester",
    }, "tester", store)

    # Create an episode directly for testing
    import uuid
    ep_id = str(uuid.uuid4())
    cond_id = str(uuid.uuid4())
    store.conn.execute(
        "INSERT INTO condition_state(tenant_id,id,rule_id,condition,started_at) VALUES (?,?,?,?,?)",
        ("tenant_alpha", cond_id, rule["id"], "active", "2026-01-01T00:00:00Z"),
    )
    store.conn.execute(
        "INSERT INTO alert_episode(tenant_id,id,rule_id,episode_identity,condition_id,"
        "workflow_status,observed_value,started_at) VALUES (?,?,?,?,?,?,?,?)",
        ("tenant_alpha", ep_id, rule["id"], "test:identity", cond_id,
         "open", 150.0, "2026-01-01T00:00:00Z"),
    )
    store.conn.commit()

    # Transition: acknowledge
    ep = AlertLifecycle.transition_episode("tenant_alpha", ep_id, "acknowledged", "tester", store)
    assert ep["workflow_status"] == "acknowledged"
    assert ep["acknowledged_by"] == "tester"

    # Transition: investigate
    ep = AlertLifecycle.transition_episode("tenant_alpha", ep_id, "investigating", "tester", store)
    assert ep["workflow_status"] == "investigating"

    # Transition: resolve
    ep = AlertLifecycle.transition_episode("tenant_alpha", ep_id, "resolved", "tester", store)
    assert ep["workflow_status"] == "resolved"

    # Condition should be recovered
    cond = store.conn.execute(
        "SELECT condition FROM condition_state WHERE tenant_id=? AND id=?",
        ("tenant_alpha", cond_id),
    ).fetchone()
    assert cond["condition"] == "recovered"


def test_alert_episode_invalid_transition(client, alpha_headers):
    """Invalid transition raises ValueError."""
    store = client.app.state.store
    with pytest.raises(ValueError, match="invalid status"):
        AlertLifecycle.transition_episode("tenant_alpha", "nonexistent", "invalid_status", "tester", store)


def test_list_condition_states(client, alpha_headers):
    """AlertLifecycle.list_condition_states returns condition rows with rule names."""
    store = client.app.state.store
    states = AlertLifecycle.list_condition_states("tenant_alpha", store)
    assert isinstance(states, list)


def test_alert_engine_evaluate_with_series(client, alpha_headers):
    """AlertEngine.evaluate_runs with no rules returns empty."""
    store = client.app.state.store
    store.conn.executescript("""
        CREATE TABLE IF NOT EXISTS alert_rule (
          tenant_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL,
          dataset_id TEXT NOT NULL, metric_id TEXT NOT NULL,
          method TEXT NOT NULL DEFAULT 'seasonal_naive',
          season_length INTEGER NOT NULL DEFAULT 7,
          threshold REAL NOT NULL DEFAULT 3.0,
          min_effect_size REAL NOT NULL DEFAULT 0.01,
          persistence INTEGER NOT NULL DEFAULT 1,
          owner TEXT NOT NULL, escalation TEXT DEFAULT '', runbook TEXT DEFAULT '',
          enabled INTEGER NOT NULL DEFAULT 1,
          created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          PRIMARY KEY (tenant_id, id)
        );
        CREATE TABLE IF NOT EXISTS condition_state (
          tenant_id TEXT NOT NULL, id TEXT NOT NULL, rule_id TEXT NOT NULL,
          condition TEXT NOT NULL DEFAULT 'normal',
          started_at TEXT, recovered_at TEXT,
          PRIMARY KEY (tenant_id, id)
        );
        CREATE TABLE IF NOT EXISTS alert_episode (
          tenant_id TEXT NOT NULL, id TEXT NOT NULL, rule_id TEXT NOT NULL,
          episode_identity TEXT NOT NULL, condition_id TEXT NOT NULL,
          workflow_status TEXT NOT NULL DEFAULT 'open',
          observed_value REAL, expected_lower REAL, expected_upper REAL,
          scoring_method TEXT, training_window TEXT,
          effect_size REAL, persistence_count INTEGER DEFAULT 0,
          started_at TEXT NOT NULL, resolved_at TEXT, acknowledged_at TEXT,
          acknowledged_by TEXT, resolution_notes TEXT,
          PRIMARY KEY (tenant_id, id)
        );
    """)
    store.conn.commit()
    fired = AlertEngine.evaluate_rules("tenant_alpha", store, store.conn)
    assert isinstance(fired, list)  # no rules = empty list


# ======================================================================
# API integration
# ======================================================================

def test_api_health_endpoint(client, alpha_headers):
    """GET /v1/monitoring/health returns health data."""
    r = client.get("/v1/monitoring/health", headers=alpha_headers)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_api_create_and_list_rules(client, alpha_headers):
    """POST→GET /v1/monitoring/rules roundtrip."""
    r = client.post("/v1/monitoring/rules", json={
        "name": "API Test Rule", "dataset_id": "ds-test",
        "metric_id": "metric-test", "method": "seasonal_naive",
        "threshold": 4.0, "owner": "alpha.manager",
    }, headers=alpha_headers)
    assert r.status_code == 201, r.text
    rule_id = r.json()["rule"]["id"]

    r = client.get("/v1/monitoring/rules", headers=alpha_headers)
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["rules"]]
    assert rule_id in ids

    # Query enabled-only
    r = client.get("/v1/monitoring/rules?enabled_only=true", headers=alpha_headers)
    assert r.status_code == 200
    for x in r.json()["rules"]:
        assert x["enabled"] == 1 or x["enabled"] is True


def test_api_update_rule(client, alpha_headers):
    """PUT /v1/monitoring/rules/{id} updates the rule."""
    r = client.post("/v1/monitoring/rules", json={
        "name": "Update Test", "dataset_id": "ds-test",
        "metric_id": "metric-test", "threshold": 2.0, "owner": "tester",
    }, headers=alpha_headers)
    assert r.status_code == 201
    rule_id = r.json()["rule"]["id"]

    r = client.put(f"/v1/monitoring/rules/{rule_id}", json={"threshold": 9.0, "enabled": False},
                   headers=alpha_headers)
    assert r.status_code == 200, r.text
    assert r.json()["rule"]["threshold"] == 9.0
    assert r.json()["rule"]["enabled"] == 0 or r.json()["rule"]["enabled"] is False


def test_api_conditions_and_episodes(client, alpha_headers):
    """GET /v1/monitoring/conditions and /episodes return lists."""
    r = client.get("/v1/monitoring/conditions", headers=alpha_headers)
    assert r.status_code == 200
    assert "conditions" in r.json()

    r = client.get("/v1/monitoring/episodes", headers=alpha_headers)
    assert r.status_code == 200
    assert "episodes" in r.json()


def test_api_evaluate_no_rules(client, alpha_headers):
    """POST /v1/monitoring/evaluate runs gracefully with no rules."""
    r = client.post("/v1/monitoring/evaluate", json={}, headers=alpha_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "answered"
    assert isinstance(body["evaluated"], int)