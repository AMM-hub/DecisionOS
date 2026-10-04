"""Unit and integration tests for WP-04 Decision Outcome Review Experience."""

import pytest
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app
from decisionos_analytics.register import (
    create_decision,
    get_decision,
    transition_status,
    DecisionStatus,
    DecisionBrief,
)


@pytest.fixture
def pilot_ctx(tmp_path):
    data_dir = tmp_path / "data"
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    store = app.state.store
    return app, client, store


def test_decision_outcome_review_flow(pilot_ctx):
    app, client, store = pilot_ctx
    tenant = "tenant_alpha"
    user = "alpha.manager"
    headers = {"X-Tenant": tenant, "X-User": user}

    # 1. Create Decision Brief
    brief = DecisionBrief(
        problem="High Queue SLA Breaches in Tier2",
        relevant_findings=["SLA breach rate is 18.5%"],
        proposed_action="Reallocate 3 support engineers from Tier1 to Tier2",
        baseline_option="Status quo staffing",
        scope="Queue Operations",
        owner=user,
        trade_offs=["Slightly increased Tier1 wait time"],
        assumptions=["Tier2 workload pattern remains stable"],
        evidence_coverage=["ev-001"],
        validation_plan="14-day post implementation review",
        counter_metrics=["m_reopen_rate"],
        expected_effect="estimated",
    )
    dec = create_decision(store.conn, tenant, "Tier2 SLA Optimization", brief, user)
    dec_id = dec.id

    # 2. Advance lifecycle: draft -> proposed -> accepted -> implementation_pending -> active -> review_due
    transition_status(store.conn, tenant, dec_id, DecisionStatus.PROPOSED, user, "propose")
    transition_status(store.conn, tenant, dec_id, DecisionStatus.ACCEPTED, user, "accept")
    transition_status(store.conn, tenant, dec_id, DecisionStatus.IMPLEMENTATION_PENDING, user, "implementing")
    transition_status(store.conn, tenant, dec_id, DecisionStatus.ACTIVE, user, "active")
    transition_status(store.conn, tenant, dec_id, DecisionStatus.REVIEW_DUE, user, "due for review")

    # 3. GET /v1/decisions/{dec_id}/outcome-comparison
    comp_res = client.get(f"/v1/decisions/{dec_id}/outcome-comparison", headers=headers)
    assert comp_res.status_code == 200
    comp_data = comp_res.json()
    assert comp_data["status"] == "review_due"
    assert comp_data["baseline"]["metric"] == "m_sla_breach_rate"
    assert "counter_metrics" in comp_data

    # 4. POST /v1/decisions/{dec_id}/outcome
    rec_res = client.post(
        f"/v1/decisions/{dec_id}/outcome",
        headers=headers,
        json={
            "measurement_window": "14d",
            "review_verdict": "supported_improvement",
            "verdict_evidence": "SLA breaches reduced from 18.5% to 11.2%",
            "observed_results": {"m_sla_breach_rate": 11.2},
            "reason": "Completed 14-day post implementation review",
        },
    )
    assert rec_res.status_code == 200
    rec_data = rec_res.json()
    assert rec_data["status"] == "evaluated"
    assert rec_data["outcome"]["review_verdict"] == "supported_improvement"

    # 5. Verify database decision state frozen and evaluated
    final_dec = get_decision(store.conn, tenant, dec_id)
    assert final_dec.status == DecisionStatus.EVALUATED
    assert final_dec.outcome.review_verdict.value == "supported_improvement"
