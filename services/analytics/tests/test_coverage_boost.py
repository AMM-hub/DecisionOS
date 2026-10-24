"""Coverage boost tests for WP-00 through WP-05 analytics modules."""

import json
import pytest
import polars as pl
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app
from decisionos_analytics.evidence import (
    capture_evidence, compute_canonical_digest, get_evidence, EvidenceError,
    EvidenceType, SupportStatus, ExactnessClass, ReproducibilityStatus, StructuredFact,
    MAX_UNSAMPLED_ROWS,
)
from decisionos_analytics.investigations import (
    create_investigation, list_investigations, get_investigation, update_investigation_status,
    add_claim, investigate_episode, SourceType, InvestigationStatus, InvestigationError,
)
from decisionos_analytics.register import (
    create_decision, get_decision, list_decisions, transition_status, bind_evidence,
    list_decision_evidence, add_amendment, record_outcome, DecisionBrief, DecisionStatus,
    CounterevidenceCheck, CounterevidenceState, BindingRole, OutcomeRecord, Verdict,
)
from decisionos_analytics.semantics import MetricDefinitionContent, MetricQueryRequest
from decisionos_analytics.store import now_iso, new_id


@pytest.fixture
def test_env(tmp_path):
    data_dir = tmp_path / "data"
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    store = app.state.store
    objects = app.state.objects
    return client, store, objects


def test_evidence_storage_and_canonical_digest(test_env):
    client, store, objects = test_env
    tenant_id = "tenant_alpha"
    user_id = "alpha.manager"

    # Create investigation
    inv = create_investigation(store, tenant_id, "Capacity Study", "Why beds full?", "ad_hoc", user_id=user_id)
    inv_id = inv["id"]

    # Setup certified metric
    defn_content = MetricDefinitionContent(
        metric_id="m_count",
        name="Count Metric",
        kind="count",
        expression={"kind": "count", "predicates": []},
        eligibility=[],
        time_basis="timestamp",
        timezone="UTC",
        dataset_id="ds_count",
    )
    query_req = MetricQueryRequest(
        metric_id="m_count",
        schema_version="1.0",
        window={"start": "2024-01-01T00:00:00Z", "end": "2024-12-31T23:59:59Z", "timezone": "UTC"},
    )

    df = pl.DataFrame({
        "timestamp": ["2024-01-01T10:00:00Z", "2024-01-01T11:00:00Z"],
        "val": [10, 20]
    })
    res = capture_evidence(
        store, objects, tenant_id, user_id, inv_id, defn_content, query_req, df, dataset_revision=1
    )
    assert res["storage_format"] == "json"
    assert res["canonical_digest"] is not None
    assert res["definition_version"] is None
    assert "definition_version_unknown" in res["quality_flags"]

    # Retrieve evidence
    ev = get_evidence(store, objects, tenant_id, res["artifact_id"])
    assert ev["storage_format"] == "json"


def test_investigations_queries_and_transitions(test_env):
    _, store, _ = test_env
    tenant_id = "tenant_alpha"
    user_id = "alpha.manager"

    inv1 = create_investigation(store, tenant_id, "Inv 1", "Q1", "ad_hoc", user_id=user_id)
    inv2 = create_investigation(store, tenant_id, "Inv 2", "Q2", "monitoring_episode", source_id="ep-100", user_id=user_id)

    # List investigations for tenant
    invs = list_investigations(store, tenant_id)
    assert len(invs) >= 2

    # Get individual investigation
    fetched = get_investigation(store, tenant_id, inv1["id"])
    assert fetched["id"] == inv1["id"]

    # Invalid status string fails
    with pytest.raises(InvestigationError):
        update_investigation_status(store, tenant_id, inv1["id"], "invalid_status", user_id=user_id)

    # Valid status transitions: open -> in_progress -> resolved -> closed
    update_investigation_status(store, tenant_id, inv1["id"], "in_progress", user_id=user_id)
    update_investigation_status(store, tenant_id, inv1["id"], "resolved", user_id=user_id)
    closed_inv = update_investigation_status(store, tenant_id, inv1["id"], "closed", user_id=user_id)
    assert closed_inv["status"] == "closed"


def test_register_outcome_and_amendments(test_env):
    _, store, _ = test_env
    tenant_id = "tenant_alpha"
    user_id = "alpha.manager"

    brief = DecisionBrief(
        problem="Problem statement",
        relevant_findings=["Finding A"],
        proposed_action="Action A",
        baseline_option="Baseline",
        scope="Global",
        owner=user_id,
        trade_offs=["Tradeoff 1"],
        assumptions=["Assumption 1"],
        evidence_coverage=["ev-1"],
        validation_plan="Plan",
        counter_metrics=["m_counter"],
        expected_effect="estimated",
    )
    ce = [CounterevidenceCheck(hypothesis="Hypo 1", state=CounterevidenceState.NOT_DETECTED, detail="Checked clean")]
    dec = create_decision(store.conn, tenant_id, "Decision 1", brief, user_id, counterevidence=ce)

    # Add amendment
    amd_dec = add_amendment(store.conn, tenant_id, dec.id, user_id, "Scope expansion", "scope", {"added": "region_b"})
    assert len(amd_dec.amendments) == 1

    # Record outcome
    outcome = OutcomeRecord(
        observed_results={"metric": 95},
        pinned_definition_version=1,
        data_revision=1,
        measurement_window="2024-Q1",
        expectation="Target > 90%",
        estimated_effect={"diff": 5},
        study_run="run-1",
        data_quality_caveats=[],
        review_verdict=Verdict.SUPPORTED_IMPROVEMENT,
        verdict_evidence="Target exceeded",
    )
    eval_dec = record_outcome(store.conn, tenant_id, dec.id, outcome, user_id, "Q1 Review")
    assert eval_dec.status == DecisionStatus.EVALUATED
    assert eval_dec.outcome.review_verdict == Verdict.SUPPORTED_IMPROVEMENT


def test_bilingual_api_endpoints(test_env):
    client, store, _ = test_env
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # Get bilingual labels dictionary
    r_dict = client.get("/v1/bilingual/labels", headers=headers)
    assert r_dict.status_code == 200
    assert "metrics" in r_dict.json()

    # Search bilingual labels (English and Arabic)
    r_search_en = client.post("/v1/bilingual/search", headers=headers, json={"query": "occupancy", "locale": "en"})
    assert r_search_en.status_code == 200
    search_data_en = r_search_en.json()
    assert "results" in search_data_en
    assert isinstance(search_data_en["results"], list)

    r_search_ar = client.post("/v1/bilingual/search", headers=headers, json={"query": "rate", "locale": "ar"})
    assert r_search_ar.status_code == 200
    search_data_ar = r_search_ar.json()
    assert "results" in search_data_ar


def test_evidence_and_investigation_error_handling(test_env):
    client, store, objects = test_env
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # 1. Non-existent investigation for evidence capture
    defn_content = MetricDefinitionContent(
        metric_id="m_err",
        name="Err Metric",
        kind="count",
        expression={"kind": "count", "predicates": []},
        eligibility=[],
        time_basis="timestamp",
        timezone="UTC",
        dataset_id="ds_err",
    )
    query_req = MetricQueryRequest(
        metric_id="m_err",
        schema_version="1.0",
        window={"start": "2024-01-01T00:00:00Z", "end": "2024-12-31T23:59:59Z", "timezone": "UTC"},
    )
    df = pl.DataFrame({"timestamp": ["2024-01-01T00:00:00Z"], "val": [1]})
    with pytest.raises(EvidenceError) as exc:
        capture_evidence(store, objects, "tenant_alpha", "alpha.manager", "inv-missing", defn_content, query_req, df, 1)
    assert exc.value.code == "investigation_not_found"

    # 2. Non-existent evidence GET -> 404
    r_ev_404 = client.get("/v1/evidence/ev-bogus", headers=headers)
    assert r_ev_404.status_code == 404

    # 3. Non-existent investigation status update -> 404
    r_inv_404 = client.post("/v1/investigations/inv-bogus/status", headers=headers, json={"status": "in_progress"})
    assert r_inv_404.status_code == 404

    # 4. Non-existent decision status update -> 404
    r_dec_404 = client.post("/v1/decisions/dec-bogus/transition", headers=headers, json={"status": "proposed"})
    assert r_dec_404.status_code == 404


def test_objectstore_and_scanning_and_monitoring_boost(test_env):
    client, store, objects = test_env
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

    # 1. ObjectStore methods
    res = objects.put_evidence_object("tenant_alpha", "ev-obj-1", b"test parquet bytes")
    fetched_bytes = objects.get_evidence_object(res["key"])
    assert fetched_bytes == b"test parquet bytes"

    # 2. Scanning module
    from decisionos_analytics.scanning import scan
    scan_res = scan("clean.csv", b"timestamp,value\n2024-01-01T00:00:00Z,10\n")
    assert scan_res.verdict == "clean"

    # 3. Monitoring endpoints
    r_health = client.get("/v1/monitoring/health", headers=headers)
    assert r_health.status_code == 200
    assert isinstance(r_health.json(), list)

    r_rules = client.get("/v1/monitoring/rules", headers=headers)
    assert r_rules.status_code == 200
    assert "rules" in r_rules.json()

    r_episodes = client.get("/v1/monitoring/episodes", headers=headers)
    assert r_episodes.status_code == 200
    assert "episodes" in r_episodes.json()
