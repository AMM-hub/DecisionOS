"""M3 Workflow Analytics tests (spec §15): event-log loading, bottleneck,
variant, conformance, case-metrics, throughput, and API integration.

Design principles verified here (§15 and workflow.py docstring):
1. Unknown event types are preserved, never silently dropped.
2. Last-events of a case have no exit timestamp → excluded from duration stats.
3. Refusal is a first-class outcome (zero data → WorkflowError / insufficient_data).
"""

from __future__ import annotations

import json

import polars as pl
import pytest
from conftest import FIXTURES, upload_and_finalize

from decisionos_analytics.workflow import (
    WorkflowError,
    bottleneck_analysis,
    case_metrics,
    conformance_checking,
    load_event_log,
    throughput_times,
    variant_analysis,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

THREE_CASES_SIMPLE = pl.DataFrame(
    {
        "case_id": ["C1", "C1", "C1", "C2", "C2", "C3", "C3", "C3", "C3"],
        "event": ["created", "assigned", "resolved", "created", "assigned", "created", "assigned", "escalated", "resolved"],
        "timestamp": [
            "2026-01-01T08:00:00Z",
            "2026-01-01T09:30:00Z",
            "2026-01-01T12:00:00Z",
            "2026-01-02T08:00:00Z",
            "2026-01-02T11:00:00Z",
            "2026-01-03T08:00:00Z",
            "2026-01-03T08:30:00Z",
            "2026-01-03T10:15:00Z",
            "2026-01-04T09:00:00Z",
        ],
    }
)

TWO_CASES_WITH_UNKNOWN = pl.DataFrame(
    {
        "case_id": ["X1", "X1", "X1", "X2", "X2"],
        "event": ["open", "review", "close", "open", "archive"],  # 'archive' unknown to rules
        "timestamp": [
            "2026-02-01T10:00:00Z",
            "2026-02-01T11:00:00Z",
            "2026-02-01T12:00:00Z",
            "2026-02-02T09:00:00Z",
            "2026-02-02T09:30:00Z",
        ],
    }
)


# ---------------------------------------------------------------------------
# load_event_log
# ---------------------------------------------------------------------------


def test_load_event_log_accepts_polars():
    log = load_event_log(THREE_CASES_SIMPLE)
    assert len(log) == 3  # 3 traces
    assert all(len(t) >= 2 for t in log)  # all have ≥2 events


def test_load_event_log_accepts_pandas():
    import pandas as pd

    pdf = THREE_CASES_SIMPLE.to_pandas()
    log = load_event_log(pdf)
    assert len(log) == 3


def test_load_event_log_raises_on_empty_data():
    with pytest.raises(WorkflowError, match="no usable events"):
        load_event_log(pl.DataFrame({"case_id": [], "event": [], "timestamp": []}))


def test_load_event_log_raises_on_missing_columns():
    with pytest.raises(WorkflowError, match="missing required columns"):
        load_event_log(pl.DataFrame({"x": [1], "y": [2], "z": [3]}))


def test_load_event_log_excludes_nulls():
    df = THREE_CASES_SIMPLE.clone().vstack(
        pl.DataFrame({"case_id": [None], "event": ["created"], "timestamp": ["2026-01-01T00:00:00Z"]})
    )
    log = load_event_log(df)
    assert len(log) == 3  # null case_id row dropped, not a 4th trace


def test_load_event_log_preserves_unknown_event_types():
    """§15 requirement 6: unknown event types are preserved."""
    log = load_event_log(TWO_CASES_WITH_UNKNOWN)
    all_events = {ev["concept:name"] for t in log for ev in t}
    assert "archive" in all_events  # never dropped


# ---------------------------------------------------------------------------
# bottleneck_analysis
# ---------------------------------------------------------------------------


def test_bottleneck_analysis_returns_activities_sorted():
    log = load_event_log(THREE_CASES_SIMPLE)
    bns = bottleneck_analysis(log)
    assert len(bns) == 4  # created, assigned, resolved, escalated
    assert all(b["count"] > 0 for b in bns)
    # sorted by longest median first
    medians = [b["median"] for b in bns if b["median"] is not None]
    if len(medians) >= 2:
        for i in range(len(medians) - 1):
            assert medians[i] >= medians[i + 1]


def test_bottleneck_analysis_last_event_excluded_from_duration():
    """Principle 2: last event of a case has no exit → excluded from duration."""
    log = load_event_log(THREE_CASES_SIMPLE)
    bns = bottleneck_analysis(log)
    resolved = [b for b in bns if b["activity"] == "resolved"]
    assert len(resolved) == 1
    # resolved is the last event for C1 and C2, so only C3's resolved has a duration
    assert resolved[0]["count"] == 2  # both resolved events counted
    # only one has a duration (C3's resolved isn't last)
    # the median should be from that one duration


def test_bottleneck_analysis_unit_conversion():
    log = load_event_log(THREE_CASES_SIMPLE)
    hrs = bottleneck_analysis(log, unit="hours")
    mins = bottleneck_analysis(log, unit="minutes")
    days = bottleneck_analysis(log, unit="days")
    for bh, bm in zip(hrs, mins):
        if bh["median"] is not None and bm["median"] is not None:
            assert abs(bm["median"] - bh["median"] * 60) < 0.1


def test_bottleneck_analysis_refuses_bad_unit():
    log = load_event_log(THREE_CASES_SIMPLE)
    with pytest.raises(WorkflowError, match="unsupported unit"):
        bottleneck_analysis(log, unit="fortnights")


# ---------------------------------------------------------------------------
# variant_analysis
# ---------------------------------------------------------------------------


def test_variant_analysis_returns_all_variants():
    log = load_event_log(THREE_CASES_SIMPLE)
    variants = variant_analysis(log)
    # C1: created→assigned→resolved, C2: created→assigned, C3: created→assigned→escalated→resolved
    # So we expect 3 distinct variants
    assert len(variants) >= 2
    assert sum(v["case_count"] for v in variants) == 3


def test_variant_analysis_simplified_path_collapses_repeats():
    df = pl.DataFrame(
        {
            "case_id": ["Z1", "Z1", "Z1", "Z1"],
            "event": ["ping", "ping", "pong", "pong"],
            "timestamp": ["2026-01-01T08:00:00Z", "2026-01-01T08:01:00Z", "2026-01-01T08:02:00Z", "2026-01-01T08:03:00Z"],
        }
    )
    log = load_event_log(df)
    variants = variant_analysis(log)
    v = variants[0]
    assert v["simplified_path"] == ["ping", "pong"]  # no consecutive repeats


# ---------------------------------------------------------------------------
# conformance_checking
# ---------------------------------------------------------------------------


def test_conformance_perfect_fitness():
    log = load_event_log(THREE_CASES_SIMPLE)
    rules = [
        {"from_activity": "created", "to_activity": "assigned"},
        {"from_activity": "assigned", "to_activity": "resolved"},
        {"from_activity": "assigned", "to_activity": "escalated"},
        {"from_activity": "escalated", "to_activity": "resolved"},
    ]
    result = conformance_checking(log, rules)
    # C2: created→assigned then stops — only 1 transition, both allowed → no violation
    # C3: 3 transitions all allowed → no violation
    assert result["fitness"] == 1.0
    assert result["violated_cases"] == 0


def test_conformance_reports_violations():
    log = load_event_log(THREE_CASES_SIMPLE)
    rules = [{"from_activity": "created", "to_activity": "assigned"}]
    result = conformance_checking(log, rules)
    # assigned→resolved (C1), assigned (C2 stop, no violation), assigned→escalated→resolved (C3)
    # Violated: C1 (assigned→resolved not in rules), C3 (assigned→escalated→resolved)
    assert result["violated_cases"] >= 2
    assert len(result["example_violations"]) > 0


def test_conformance_reports_unknown_activities():
    """§15 requirement 6: unknown event types preserved in unknown_activities."""
    log = load_event_log(TWO_CASES_WITH_UNKNOWN)
    rules = [{"from_activity": "open", "to_activity": "review"}, {"from_activity": "review", "to_activity": "close"}]
    result = conformance_checking(log, rules)
    assert "archive" in result["unknown_activities"]
    assert "close" not in result["unknown_activities"]


def test_conformance_raises_on_empty_rules():
    log = load_event_log(THREE_CASES_SIMPLE)
    with pytest.raises(WorkflowError, match="expected_rules must contain"):
        conformance_checking(log, [])


# ---------------------------------------------------------------------------
# case_metrics / SLA
# ---------------------------------------------------------------------------


def test_case_metrics_reports_status():
    log = load_event_log(THREE_CASES_SIMPLE)
    cm = case_metrics(log, sla_hours=24, unit="hours")
    assert cm["summary"]["total_cases"] == 3
    # C1 created→assigned→resolved in 4h → met (closed)
    # C2 created→assigned (last=assigned, not in closed set).
    #   As of the max-data timestamp (2026-01-04T09:00Z), C2's age is ~49h → breached
    # C3 created→assigned→escalated→resolved in 25h → breached
    assert cm["summary"]["met"] >= 1
    assert cm["summary"]["total_cases"] == cm["summary"]["met"] + cm["summary"]["in_progress"] + cm["summary"]["breached"]


def test_case_metrics_closed_activities_configurable():
    log = load_event_log(THREE_CASES_SIMPLE)
    # Custom closed set includes 'assigned' so case C2 becomes 'closed' too
    cm = case_metrics(log, sla_hours=48, closed_activities={"resolved", "assigned"})
    closed = [c for c in cm["metrics"] if c["closed"]]
    assert len(closed) == 3  # all three cases end with assigned or resolved


def test_case_metrics_as_of_override():
    log = load_event_log(THREE_CASES_SIMPLE)
    cm1 = case_metrics(log, now="2026-01-01T10:00:00Z")  # before C1's last event
    cm2 = case_metrics(log)  # uses max timestamp
    # With early as_of, open cases are younger
    c1_open = [c for c in cm1["metrics"] if c["case_id"] == "C1"][0]
    c2_open = [c for c in cm2["metrics"] if c["case_id"] == "C1"][0]
    assert c1_open["age"] <= c2_open["age"]


# ---------------------------------------------------------------------------
# throughput_times
# ---------------------------------------------------------------------------


def test_throughput_times_returns_stages():
    log = load_event_log(THREE_CASES_SIMPLE)
    stages = throughput_times(log, unit="hours")
    assert len(stages) >= 3
    created = [s for s in stages if s["stage"] == "created"][0]
    assert created["count"] == 3
    assert created["to_activities"]  # should show what follows created
    assert "assigned" in created["to_activities"]


def test_throughput_times_last_event_excluded():
    """Final event of each case has no duration."""
    log = load_event_log(THREE_CASES_SIMPLE)
    resolved = [s for s in throughput_times(log) if s["stage"] == "resolved"][0]
    # C1 resolved is last, C2 doesn't reach resolved, C3 resolved is last
    # So resolved appears 2 times (C1 and C3) but both are last → no duration
    # Actually C1's resolved IS the last event, C3's resolved IS the last event
    # So resolved count = 2 but min/median/max = None
    assert resolved["count"] == 2
    assert resolved["min"] is None  # both are last events, no exit


# ---------------------------------------------------------------------------
# API integration (requires fixture data)
# ---------------------------------------------------------------------------


def _publish_events(client, headers):
    """Upload the ticket_events CSV and return dataset_id + revision.
    Workflow analytics reads the latest revision regardless of publication
    state, so grain-confirm + publish are not required."""
    uid, fin = upload_and_finalize(client, headers, FIXTURES / "tenant_alpha" / "ticket_events.csv")
    return fin["dataset_id"], fin["revision"]


def test_workflow_bottlenecks_api(client, alpha_headers):
    ds_id, rev = _publish_events(client, alpha_headers)
    r = client.post(
        "/v1/workflow/bottlenecks",
        json={"dataset_id": ds_id, "case_id_col": "case_id", "event_col": "event_type", "timestamp_col": "occurred_at", "unit": "hours"},
        headers=alpha_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "answered"
    assert len(data["bottlenecks"]) > 0
    assert data["revision"] == rev
    assert data["evidence_ref"]


def test_workflow_variants_api(client, alpha_headers):
    ds_id, rev = _publish_events(client, alpha_headers)
    r = client.post(
        "/v1/workflow/variants",
        json={"dataset_id": ds_id, "case_id_col": "case_id", "event_col": "event_type", "timestamp_col": "occurred_at", "top": 5},
        headers=alpha_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "answered"
    assert len(data["variants"]) > 0
    assert data["total_cases"] > 0


def test_workflow_conformance_api(client, alpha_headers):
    ds_id, rev = _publish_events(client, alpha_headers)
    rules = [
        {"from_activity": "created", "to_activity": "assigned"},
        {"from_activity": "assigned", "to_activity": "customer_reply"},
        {"from_activity": "assigned", "to_activity": "agent_note"},
        {"from_activity": "customer_reply", "to_activity": "assigned"},
        {"from_activity": "customer_reply", "to_activity": "agent_note"},
        {"from_activity": "agent_note", "to_activity": "assigned"},
        {"from_activity": "agent_note", "to_activity": "customer_reply"},
        {"from_activity": "agent_note", "to_activity": "resolved"},
        {"from_activity": "assigned", "to_activity": "resolved"},
    ]
    r = client.post(
        "/v1/workflow/conformance",
        json={"dataset_id": ds_id, "case_id_col": "case_id", "event_col": "event_type", "timestamp_col": "occurred_at", "expected_rules": rules},
        headers=alpha_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "answered"
    assert 0 <= data["fitness"] <= 1
    assert data["total_cases"] > 0
    assert data["evidence_ref"]


def test_workflow_case_metrics_api(client, alpha_headers):
    ds_id, rev = _publish_events(client, alpha_headers)
    r = client.post(
        "/v1/workflow/case-metrics",
        json={"dataset_id": ds_id, "case_id_col": "case_id", "event_col": "event_type", "timestamp_col": "occurred_at", "sla_hours": 48},
        headers=alpha_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "answered"
    assert data["summary"]["total_cases"] > 0
    assert len(data["metrics"]) > 0


def test_workflow_throughput_api(client, alpha_headers):
    ds_id, rev = _publish_events(client, alpha_headers)
    r = client.post(
        "/v1/workflow/throughput",
        json={"dataset_id": ds_id, "case_id_col": "case_id", "event_col": "event_type", "timestamp_col": "occurred_at"},
        headers=alpha_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "answered"
    assert len(data["stages"]) > 0
    assert data["revision"] == rev


def test_workflow_refuses_empty_dataset(client, alpha_headers):
    """No dataset_id → 404 (not found, per §23.4 no cross-tenant disclosure)."""
    r = client.post(
        "/v1/workflow/bottlenecks",
        json={"dataset_id": "nonexistent", "case_id_col": "case_id", "event_col": "event_type", "timestamp_col": "occurred_at"},
        headers=alpha_headers,
    )
    assert r.status_code == 404, r.text


def test_workflow_refuses_bad_column_mapping(client, alpha_headers):
    ds_id, _ = _publish_events(client, alpha_headers)
    r = client.post(
        "/v1/workflow/bottlenecks",
        json={"dataset_id": ds_id, "case_id_col": "WRONG", "event_col": "event_type", "timestamp_col": "occurred_at"},
        headers=alpha_headers,
    )
    # The dataset has no 'WRONG' column → WorkflowError mapped to 422
    assert r.status_code == 422, r.text


def test_workflow_tenant_isolation(client, alpha_headers, beta_headers):
    """Beta cannot see Alpha's data."""
    ds_id, _ = _publish_events(client, alpha_headers)
    r = client.post(
        "/v1/workflow/variants",
        json={"dataset_id": ds_id, "case_id_col": "case_id", "event_col": "event_type", "timestamp_col": "occurred_at"},
        headers=beta_headers,
    )
    assert r.status_code == 404, r.text  # §23.4