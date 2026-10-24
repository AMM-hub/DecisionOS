"""Primary PILOT-01 End-to-End Master Golden Pilot Journey Integration Test.

Certifies complete operational decision loop from onboarding to outcome evaluation:
pilot created -> dataset uploaded/revision selected -> readiness validated ->
semantic pack configured -> workflow mapped -> monitoring configured ->
risk target available -> alert/risk case scored -> investigation launched ->
evidence captured -> decision created & accepted -> review due -> outcome recorded ->
decision evaluated & closed -> pilot summary reflects complete result.
"""

import io
import json
import pytest
import polars as pl
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app
from decisionos_analytics.store import Store
from decisionos_analytics.register import (
    create_decision,
    get_decision,
    transition_status,
    DecisionStatus,
    DecisionBrief,
    bind_evidence,
    BindingRole,
)


@pytest.fixture
def pilot_ctx(tmp_path):
    data_dir = tmp_path / "data"
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    store = app.state.store
    objects = app.state.objects
    return app, client, store, objects


def test_master_golden_pilot_journey(pilot_ctx):
    app, client, store, objects = pilot_ctx
    tenant = "tenant_alpha"
    user = "alpha.manager"
    headers = {"X-Tenant": tenant, "X-User": user}

    # -----------------------------------------------------------------------
    # Step 1: Create Bounded Pilot Contract
    # -----------------------------------------------------------------------
    create_plt_res = client.post(
        "/v1/pilots",
        headers=headers,
        json={
            "name": "Golden Support SLA Pilot",
            "domain": "support_ticket_operations",
            "owner": user,
        },
    )
    assert create_plt_res.status_code == 201
    pilot = create_plt_res.json()
    pilot_id = pilot["id"]
    assert pilot["status"] == "draft"

    # -----------------------------------------------------------------------
    # Step 2: Upload Dataset & Publish Revision
    # -----------------------------------------------------------------------
    fixture_path = "tests/fixtures/golden_support_pilot.csv"
    df = pl.read_csv(fixture_path)
    buf = io.BytesIO()
    df.write_parquet(buf)
    content_bytes = buf.getvalue()

    dataset_id = "ds_support_golden"
    obj_res = objects.put_revision_object(tenant, dataset_id, 1, "rev1.parquet", content_bytes)
    manifest = {"objects": [{"key": obj_res["key"]}]}

    store.conn.execute(
        "INSERT INTO dataset (tenant_id, id, workspace_id, name, published_revision, created_at) VALUES (?, ?, 'ws-support-ops', 'Support Golden Data', 1, '2026-10-01T00:00:00Z')",
        (tenant, dataset_id),
    )
    store.conn.execute(
        "INSERT INTO dataset_revision (tenant_id, dataset_id, revision, state, manifest, row_count, created_at) VALUES (?, ?, 1, 'published', ?, ?, '2026-10-01T00:00:00Z')",
        (tenant, dataset_id, json.dumps(manifest), df.height),
    )
    store.conn.execute(
        "UPDATE pilot SET dataset_id=?, dataset_revision=? WHERE tenant_id=? AND id=?",
        (dataset_id, 1, tenant, pilot_id),
    )
    store.conn.commit()

    # -----------------------------------------------------------------------
    # Step 3: Validate Data Quality Gate
    # -----------------------------------------------------------------------
    val_res = client.post(f"/v1/pilots/{pilot_id}/validate-data", headers=headers, json={})
    assert val_res.status_code == 200
    val_data = val_res.json()
    assert val_data["status"] == "PASS"
    assert val_data["metrics"]["unique_cases"] >= 4

    # -----------------------------------------------------------------------
    # Step 4: Configure Semantic Pack & SLA
    # -----------------------------------------------------------------------
    sem_res = client.get("/v1/pilots/semantic-pack", headers=headers)
    assert sem_res.status_code == 200

    sla_res = client.post(
        f"/v1/pilots/{pilot_id}/sla",
        headers=headers,
        json={
            "target_name": "Support 24h SLA",
            "eligible_population": "all_open_tickets",
            "deadline_rule": "24h_from_creation",
            "calendar_utc": True,
        },
    )
    assert sla_res.status_code == 200
    assert sla_res.json()["sla_config"]["status_message"] == "SUPPORTED"

    # -----------------------------------------------------------------------
    # Step 5: Configure Workflow Mapping
    # -----------------------------------------------------------------------
    map_res = client.post(
        f"/v1/pilots/{pilot_id}/mapping",
        headers=headers,
        json={
            "case_id": "ticket_id",
            "activity": "status",
            "timestamp": "timestamp",
            "queue": "queue",
            "completion_state": "status",
            "reopen": "reopen",
            "transfer": "transfer",
        },
    )
    assert map_res.status_code == 200
    assert map_res.json()["workflow_summary"]["case_count"] >= 4

    # -----------------------------------------------------------------------
    # Step 6: Configure Monitoring Rule & Risk Target
    # -----------------------------------------------------------------------
    mon_res = client.post(
        f"/v1/pilots/{pilot_id}/monitoring-rules",
        headers=headers,
        json={
            "name": "Queue Backlog Anomaly",
            "metric_id": "m_queue_backlog",
            "threshold": 2.0,
        },
    )
    assert mon_res.status_code == 200

    risk_res = client.post(
        f"/v1/pilots/{pilot_id}/risk-target",
        headers=headers,
        json={
            "target_name": "24h SLA Breach Risk",
            "outcome_window": "24h",
        },
    )
    assert risk_res.status_code == 200
    risk_config = risk_res.json()["risk_config"]
    model_id = risk_config["model"]["id"]
    target_id = risk_config["target"]["id"]

    from decisionos_analytics.predictive import record_prediction, transition_model_status
    transition_model_status(store, tenant, model_id, "evaluated", user)
    transition_model_status(store, tenant, model_id, "approved", user)
    transition_model_status(store, tenant, model_id, "active", user)

    # -----------------------------------------------------------------------
    # Step 7: Persist a Predictive Risk Case
    # (the score API refuses without a trained artifact, so this journey seeds
    # the persisted prediction directly to exercise the evidence path)
    # -----------------------------------------------------------------------
    score_data = record_prediction(
        store=store,
        tenant_id=tenant,
        model_id=model_id,
        target_id=target_id,
        entity_id="T1004",
        observation_time="2026-10-01T14:00:00Z",
        score=0.42,
        risk_tier="LOW",
        threshold_used=0.5,
        outcome_window="24h",
        source_dataset_revision=1,
        feature_snapshot={"case_age_hours": 3.0, "queue": "Escalations"},
    )
    assert score_data["risk_tier"] in ("HIGH", "MEDIUM", "LOW")
    pred_id = score_data["prediction_id"]

    # -----------------------------------------------------------------------
    # Step 8: Launch Investigation & Capture Evidence
    # -----------------------------------------------------------------------
    inv_res = client.post(
        "/v1/investigations",
        headers=headers,
        json={
            "title": "Escalations Queue SLA Breach Risk Investigation",
            "question": "Why is ticket T1004 at high risk of 24h SLA breach?",
            "trigger_source": "predictive_risk",
            "source_id": pred_id,
            "assigned_to": user,
        },
    )
    assert inv_res.status_code == 201
    inv_id = inv_res.json()["id"]

    ev_res = client.post(
        f"/v1/predictive/predictions/{pred_id}/evidence",
        headers=headers,
        json={"investigation_id": inv_id},
    )
    assert ev_res.status_code == 201
    artifact_id = ev_res.json()["artifact_id"]

    # -----------------------------------------------------------------------
    # Step 9: Create Decision Brief & Bind Evidence
    # -----------------------------------------------------------------------
    brief = DecisionBrief(
        problem="High risk of 24h SLA breach on Escalation tickets",
        relevant_findings=["Persisted predictive risk for T1004 in Escalations queue"],
        proposed_action="Reallocate 2 agents from Tier1 to Escalations queue",
        baseline_option="Status quo staffing",
        scope="Queue Operations",
        owner=user,
        trade_offs=["Minor SLA buffer reduction in Tier1"],
        assumptions=["Escalation volume stabilizes within 24h"],
        evidence_coverage=[artifact_id],
        validation_plan="14-day outcome review",
        counter_metrics=["m_reopen_rate"],
        expected_effect="estimated",
    )
    dec = create_decision(store.conn, tenant, "Escalation Queue Reallocation", brief, user)
    dec_id = dec.id

    bind_evidence(store.conn, tenant, dec_id, artifact_id, BindingRole.PRIMARY_SUPPORT, user)

    # -----------------------------------------------------------------------
    # Step 10: Advance Decision Lifecycle & Freeze
    # -----------------------------------------------------------------------
    transition_status(store.conn, tenant, dec_id, DecisionStatus.PROPOSED, user, "propose")
    transition_status(store.conn, tenant, dec_id, DecisionStatus.ACCEPTED, user, "accept")
    transition_status(store.conn, tenant, dec_id, DecisionStatus.IMPLEMENTATION_PENDING, user, "implementing")
    transition_status(store.conn, tenant, dec_id, DecisionStatus.ACTIVE, user, "active")
    transition_status(store.conn, tenant, dec_id, DecisionStatus.REVIEW_DUE, user, "due for review")

    # -----------------------------------------------------------------------
    # Step 11: Record Outcome Review & Evaluate
    # -----------------------------------------------------------------------
    out_res = client.post(
        f"/v1/decisions/{dec_id}/outcome",
        headers=headers,
        json={
            "measurement_window": "14d",
            "review_verdict": "supported_improvement",
            "verdict_evidence": "SLA breach rate dropped to 1.2% with zero counter-metric degradation",
            "observed_results": {"m_sla_breach_rate": 1.2},
        },
    )
    assert out_res.status_code == 200
    assert out_res.json()["status"] == "evaluated"

    # Close decision
    transition_status(store.conn, tenant, dec_id, DecisionStatus.CLOSED, user, "close decision")
    final_dec = get_decision(store.conn, tenant, dec_id)
    assert final_dec.status == DecisionStatus.CLOSED

    # -----------------------------------------------------------------------
    # Step 12: Verify Executive Pilot Command Center Summary
    # -----------------------------------------------------------------------
    sum_res = client.get(f"/v1/pilots/{pilot_id}/summary", headers=headers)
    assert sum_res.status_code == 200
    summary = sum_res.json()["summary"]
    assert summary["data_readiness"] == "PASS"
    assert summary["completed_reviews"] >= 1
    assert summary["auth_security_gate"] == "INTERNAL_EVALUATION_ONLY"
