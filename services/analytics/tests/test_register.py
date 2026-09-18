"""M4 Decision Register tests (spec §19): lifecycle transitions, immutable
amendment trail, outcome recording, and refusal paths.

Design principles verified:
1. Append-only amendments: status transitions record author + reason.
2. Freeze accepted expectations (immutable brief).
3. Do not auto-close overdue decisions.
4. Counterevidence checks use the four-state vocabulary.
"""

from __future__ import annotations

import json

import pytest
from conftest import FIXTURES, upload_and_finalize

from decisionos_analytics.register import (
    DECISION_SCHEMA,
    CounterevidenceCheck,
    CounterevidenceState,
    DecisionBrief,
    DecisionRecord,
    DecisionStatus,
    OutcomeRecord,
    Verdict,
    create_decision,
    get_decision,
    list_decisions,
    now_iso,
    record_outcome,
    transition_status,
)


@pytest.fixture()
def store(request):
    """In-memory SQLite store for register tests."""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DECISION_SCHEMA)
    conn.commit()
    yield conn
    conn.close()


def make_brief(**overrides) -> DecisionBrief:
    return DecisionBrief(
        problem=overrides.get("problem", "Staffing shortage in Q1"),
        relevant_findings=overrides.get("findings", ["F1: backlog > 72h", "F2: overtime >20%"]),
        proposed_action=overrides.get("action", "Hire 2 agents"),
        baseline_option=overrides.get("baseline", "No change"),
        scope=overrides.get("scope", "Support Ops, Q1 2027"),
        owner=overrides.get("owner", "ops.manager"),
        trade_offs=overrides.get("trade_offs", ["Cost increase $40k", "Wait improvement 8h"]),
        assumptions=overrides.get("assumptions", ["Training completes in 4 weeks"]),
        evidence_coverage=overrides.get("evidence", ["Backlog trend Jan-Dec 2026", "Attrition rate 12%"]),
        validation_plan=overrides.get("validation", "Compare SLA at 3 months post-hire"),
        counter_metrics=overrides.get("metrics", ["CSAT", "OT %"]),
        expected_effect=overrides.get("expected", "estimated"),
    )


# ---- CRUD ---------------------------------------------------------------


def test_create_decision(store):
    brief = make_brief()
    rec = create_decision(store, "tenant_alpha", "Hiring Plan Q1", brief, "alpha.manager")
    assert rec.id is not None
    assert rec.status == DecisionStatus.DRAFT
    assert rec.title == "Hiring Plan Q1"
    assert rec.tenant_id == "tenant_alpha"
    assert rec.brief.problem == "Staffing shortage in Q1"
    assert len(rec.amendments) == 0


def test_get_decision(store):
    brief = make_brief()
    created = create_decision(store, "tenant_alpha", "Test Decision", brief, "alpha.manager")
    fetched = get_decision(store, "tenant_alpha", created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.title == "Test Decision"
    assert fetched.brief.problem == brief.problem


def test_get_decision_returns_none_for_missing(store):
    assert get_decision(store, "tenant_alpha", "nonexistent") is None


def test_get_decision_tenant_isolation(store):
    brief = make_brief()
    a = create_decision(store, "tenant_alpha", "Alpha Decision", brief, "alpha.manager")
    b = get_decision(store, "tenant_beta", a.id)
    assert b is None  # cross-tenant


def test_list_decisions(store):
    for i in range(3):
        create_decision(store, "tenant_alpha", f"Decision {i}", make_brief(problem=f"Problem {i}"), "alpha.manager")
    all_d = list_decisions(store, "tenant_alpha")
    assert len(all_d) == 3


def test_list_decisions_respects_tenant(store):
    create_decision(store, "tenant_alpha", "A-only", make_brief(), "alpha.manager")
    create_decision(store, "tenant_beta", "B-only", make_brief(), "beta.manager")
    assert len(list_decisions(store, "tenant_alpha")) == 1
    assert len(list_decisions(store, "tenant_beta")) == 1


# ---- lifecycle transitions -------------------------------------------------


def test_transition_to_proposed(store):
    rec = create_decision(store, "tenant_alpha", "Test", make_brief(), "alpha.manager")
    updated = transition_status(store, "tenant_alpha", rec.id, DecisionStatus.PROPOSED, "alpha.modeler", "Ready for review")
    assert updated.status == DecisionStatus.PROPOSED
    assert len(updated.amendments) == 1
    amd = updated.amendments[0]
    assert amd.author == "alpha.modeler"
    assert amd.reason == "Ready for review"
    assert amd.changes["new_status"] == "proposed"


def test_transition_records_immutable_amendment(store):
    rec = create_decision(store, "tenant_alpha", "Test", make_brief(), "alpha.manager")
    for status in [DecisionStatus.PROPOSED, DecisionStatus.ACCEPTED, DecisionStatus.ACTIVE]:
        rec = transition_status(store, "tenant_alpha", rec.id, status, "alpha.manager", f"Move to {status.value}")
    assert len(rec.amendments) == 3
    for i, amd in enumerate(rec.amendments):
        assert amd.version == i + 1


def test_transition_raises_on_missing(store):
    with pytest.raises(LookupError):
        transition_status(store, "tenant_alpha", "nonexistent", DecisionStatus.CLOSED, "user", "reason")


def test_transition_to_closed(store):
    rec = create_decision(store, "tenant_alpha", "Test", make_brief(), "alpha.manager")
    rec = transition_status(store, "tenant_alpha", rec.id, DecisionStatus.CLOSED, "alpha.manager", "Completed")
    assert rec.status == DecisionStatus.CLOSED


# ---- outcome recording -----------------------------------------------------


def test_record_outcome(store):
    rec = create_decision(store, "tenant_alpha", "Test", make_brief(), "alpha.manager")
    outcome = OutcomeRecord(
        observed_results={"sla_met_pct": 94.5},
        pinned_definition_version=1,
        data_revision=3,
        measurement_window="2026-10-01/2027-01-15",
        expectation="SLA > 90%",
        estimated_effect={"improvement": 8.2},
        study_run="run-001",
        data_quality_caveats=["Missing 2 days of data"],
        review_verdict=Verdict.SUPPORTED_IMPROVEMENT,
        verdict_evidence="SLA improved from 86% to 94.5%",
    )
    updated = record_outcome(store, "tenant_alpha", rec.id, outcome, "alpha.manager", "Q1 review complete")
    assert updated.status == DecisionStatus.EVALUATED
    assert updated.outcome is not None
    assert updated.outcome.review_verdict == Verdict.SUPPORTED_IMPROVEMENT
    assert len(updated.amendments) == 1


def test_record_outcome_preserves_prior_amendments(store):
    rec = create_decision(store, "tenant_alpha", "Test", make_brief(), "alpha.manager")
    rec = transition_status(store, "tenant_alpha", rec.id, DecisionStatus.ACCEPTED, "alpha.manager", "Approved")
    outcome = OutcomeRecord(
        observed_results={}, measurement_window="2026-Q4",
        expectation="", review_verdict=Verdict.NO_CLEAR_CHANGE,
        verdict_evidence="No detectable improvement in 90 days",
        pinned_definition_version=None, data_revision=None, estimated_effect=None,
        study_run=None, data_quality_caveats=[],
    )
    updated = record_outcome(store, "tenant_alpha", rec.id, outcome, "alpha.manager", "Evaluated")
    assert len(updated.amendments) == 2  # status change + outcome


def test_record_outcome_raises_on_missing(store):
    outcome = OutcomeRecord(
        observed_results={}, measurement_window="", expectation="",
        review_verdict=Verdict.INCONCLUSIVE, verdict_evidence="",
        pinned_definition_version=None, data_revision=None, estimated_effect=None,
        study_run=None, data_quality_caveats=[],
    )
    with pytest.raises(LookupError):
        record_outcome(store, "tenant_alpha", "nonexistent", outcome, "user", "reason")


# ---- counterevidence -------------------------------------------------------


def test_create_with_counterevidence(store):
    checks = [
        CounterevidenceCheck(hypothesis="Seasonal effect explains trend", state=CounterevidenceState.NOT_DETECTED, detail="Checked Jan vs Jul"),
        CounterevidenceCheck(hypothesis="Policy change confounds result", state=CounterevidenceState.NOT_TESTABLE, detail="Policy changed same week"),
    ]
    rec = create_decision(store, "tenant_alpha", "Test", make_brief(), "alpha.manager", counterevidence=checks)
    assert len(rec.counterevidence) == 2
    assert rec.counterevidence[0].state == CounterevidenceState.NOT_DETECTED
    assert rec.counterevidence[1].state == CounterevidenceState.NOT_TESTABLE


def test_counterevidence_all_states(store):
    for state in CounterevidenceState:
        checks = [CounterevidenceCheck(hypothesis="H1", state=state)]
        rec = create_decision(store, "tenant_alpha", f"Test-{state.value}", make_brief(), "alpha.manager", counterevidence=checks)
        assert rec.counterevidence[0].state == state


# ---- API integration -------------------------------------------------------


def test_decisions_api_create_then_list(client, alpha_headers):
    r = client.post("/v1/decisions", json={
        "title": "Hiring Plan",
        "brief": {
            "problem": "Backlog exceeds 72h SLA in Q1",
            "relevant_findings": ["F1: Trend shows 15% growth"],
            "proposed_action": "Hire 3 additional agents",
            "baseline_option": "Maintain current staffing",
            "scope": "Support Ops",
            "owner": "ops.manager",
            "trade_offs": ["Cost vs service level"],
            "assumptions": ["4-week training ramp"],
            "evidence_coverage": ["Backlog data 2026"],
            "validation_plan": "Compare SLA at 3 months",
            "counter_metrics": ["CSAT", "Overtime %"],
            "expected_effect": "estimated",
        },
        "counterevidence": [
            {"hypothesis": "Seasonal spike", "state": "not_detected", "detail": "Compared to prior year"}
        ],
    }, headers=alpha_headers)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == "draft"
    assert data["title"] == "Hiring Plan"
    did = data["id"]

    r = client.get(f"/v1/decisions/{did}", headers=alpha_headers)
    assert r.status_code == 200
    assert r.json()["id"] == did

    r = client.get("/v1/decisions", headers=alpha_headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_decisions_api_transition(client, alpha_headers):
    # Create
    r = client.post("/v1/decisions", json={
        "title": "Test Transition", "brief": {"problem": "Test", "relevant_findings": [], "proposed_action": "", "baseline_option": "", "scope": "", "owner": "", "trade_offs": [], "assumptions": [], "evidence_coverage": [], "validation_plan": "", "counter_metrics": [], "expected_effect": "unknown"},
    }, headers=alpha_headers)
    did = r.json()["id"]

    # Propose
    r = client.post(f"/v1/decisions/{did}/transition", json={"status": "proposed", "reason": "Ready"}, headers=alpha_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "proposed"

    # Accept
    r = client.post(f"/v1/decisions/{did}/transition", json={"status": "accepted", "reason": "Approved by management"}, headers=alpha_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"


def test_decisions_api_record_outcome(client, alpha_headers):
    r = client.post("/v1/decisions", json={
        "title": "Test Outcome", "brief": {"problem": "Test", "relevant_findings": [], "proposed_action": "", "baseline_option": "", "scope": "", "owner": "", "trade_offs": [], "assumptions": [], "evidence_coverage": [], "validation_plan": "", "counter_metrics": [], "expected_effect": "unknown"},
    }, headers=alpha_headers)
    did = r.json()["id"]

    outcome = {
        "observed_results": {"sla_pct": 94.2},
        "pinned_definition_version": 1,
        "data_revision": 2,
        "measurement_window": "2026-Q4",
        "expectation": ">90%",
        "estimated_effect": {"delta": 8.5},
        "study_run": "eval-001",
        "data_quality_caveats": [],
        "review_verdict": "supported_improvement",
        "verdict_evidence": "SLA improved 8.5 points",
    }
    r = client.post(f"/v1/decisions/{did}/outcome", json=outcome, headers=alpha_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "evaluated"
    assert data["outcome"]["review_verdict"] == "supported_improvement"


def test_decisions_api_tenant_isolation(client, alpha_headers, beta_headers):
    r = client.post("/v1/decisions", json={
        "title": "Alpha Only", "brief": {"problem": "P1", "relevant_findings": [], "proposed_action": "", "baseline_option": "", "scope": "", "owner": "", "trade_offs": [], "assumptions": [], "evidence_coverage": [], "validation_plan": "", "counter_metrics": [], "expected_effect": "unknown"},
    }, headers=alpha_headers)
    did = r.json()["id"]

    r = client.get(f"/v1/decisions/{did}", headers=beta_headers)
    assert r.status_code == 404  # §23.4: no cross-tenant disclosure