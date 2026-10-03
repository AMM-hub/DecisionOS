"""DOS-QA-001 Permanent Security Regression Test Suite.

Verifies cross-tenant isolation and authentication behavior across all six
previously vulnerable routes against the live FastAPI application:
1. POST /v1/scenarios/solve
2. POST /v1/decisions
3. GET /v1/decisions
4. GET /v1/decisions/{id}
5. POST /v1/decisions/{id}/transition
6. POST /v1/decisions/{id}/outcome
"""

from __future__ import annotations

import pytest


def test_database_integrity_and_pragmas(client):
    store = client.app.state.store
    fk = store.conn.execute("PRAGMA foreign_keys").fetchone()[0]
    integrity = store.conn.execute("PRAGMA integrity_check").fetchone()[0]
    assert fk in (1, "1", True), f"Expected foreign_keys=1, got {fk}"
    assert integrity == "ok", f"Expected integrity_check='ok', got {integrity}"


@pytest.fixture
def solve_payload():
    return {
        "template": "reallocate-capacity",
        "groups": ["G1"],
        "queues": ["Q1"],
        "periods": [1],
        "segments": [1],
        "eligibility": {"G1,Q1": True},
        "regular_hours": {"G1,1": 160.0},
        "overtime_cap": {"G1,1": 40.0},
        "arrivals": {"Q1,1": 100.0},
        "opening_backlog": {"Q1": 0.0},
        "segment_width": {"G1,Q1,1,1": 160.0},
        "marginal_rate": {"G1,Q1,1,1": 1.0},
        "regular_cost": {"G1,1": 10.0},
        "overtime_cost": {"G1,1": 15.0},
        "backlog_penalty": {"Q1,1": 5.0},
    }


@pytest.fixture
def decision_brief_payload():
    return {
        "title": "Security Isolation Test Brief",
        "brief": {
            "problem": "Testing isolation",
            "relevant_findings": [],
            "proposed_action": "Action A",
            "baseline_option": "Baseline",
            "scope": "Scope",
            "owner": "alpha.manager",
            "trade_offs": [],
            "assumptions": [],
            "evidence_coverage": [],
            "validation_plan": "Plan",
            "counter_metrics": [],
            "expected_effect": "unknown",
        },
    }


# ============================================================================
# 1. POST /v1/scenarios/solve
# ============================================================================

def test_solve_allowed_valid_user(client, solve_payload):
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
    res = client.post("/v1/scenarios/solve", json=solve_payload, headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] in ("optimal", "feasible_time_limited", "infeasible")


def test_solve_denied_wrong_tenant(client, solve_payload):
    # alpha.manager belongs to tenant_alpha, requesting tenant_beta
    headers = {"X-Tenant": "tenant_beta", "X-User": "alpha.manager"}
    res = client.post("/v1/scenarios/solve", json=solve_payload, headers=headers)
    assert res.status_code == 404
    assert res.json() == {"detail": "not found"}


def test_solve_denied_wrong_user(client, solve_payload):
    # beta.manager belongs to tenant_beta, requesting tenant_alpha
    headers = {"X-Tenant": "tenant_alpha", "X-User": "beta.manager"}
    res = client.post("/v1/scenarios/solve", json=solve_payload, headers=headers)
    assert res.status_code == 404
    assert res.json() == {"detail": "not found"}


def test_solve_missing_user(client, solve_payload):
    headers = {"X-Tenant": "tenant_alpha"}
    res = client.post("/v1/scenarios/solve", json=solve_payload, headers=headers)
    assert res.status_code == 401


def test_solve_invalid_user(client, solve_payload):
    headers = {"X-Tenant": "tenant_alpha", "X-User": "unknown_user"}
    res = client.post("/v1/scenarios/solve", json=solve_payload, headers=headers)
    assert res.status_code == 401


# ============================================================================
# 2. POST /v1/decisions
# ============================================================================

def test_create_decision_allowed_valid_user(client, decision_brief_payload):
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
    res = client.post("/v1/decisions", json=decision_brief_payload, headers=headers)
    assert res.status_code == 201
    assert "id" in res.json()
    assert res.json()["status"] == "draft"


def test_create_decision_denied_wrong_tenant_zero_db_records(client, decision_brief_payload):
    from decisionos_analytics.register import DECISION_SCHEMA
    store = client.app.state.store
    store.conn.executescript(DECISION_SCHEMA)
    count_before = store.conn.execute("SELECT count(*) FROM decision").fetchone()[0]

    headers = {"X-Tenant": "tenant_beta", "X-User": "alpha.manager"}
    res = client.post("/v1/decisions", json=decision_brief_payload, headers=headers)
    assert res.status_code == 404
    assert res.json() == {"detail": "not found"}

    count_after = store.conn.execute("SELECT count(*) FROM decision").fetchone()[0]
    assert count_after == count_before, "Cross-tenant denied decision create must write ZERO records"


def test_create_decision_denied_wrong_user_zero_db_records(client, decision_brief_payload):
    from decisionos_analytics.register import DECISION_SCHEMA
    store = client.app.state.store
    store.conn.executescript(DECISION_SCHEMA)
    count_before = store.conn.execute("SELECT count(*) FROM decision").fetchone()[0]

    headers = {"X-Tenant": "tenant_alpha", "X-User": "beta.manager"}
    res = client.post("/v1/decisions", json=decision_brief_payload, headers=headers)
    assert res.status_code == 404
    assert res.json() == {"detail": "not found"}

    count_after = store.conn.execute("SELECT count(*) FROM decision").fetchone()[0]
    assert count_after == count_before, "Cross-tenant denied decision create must write ZERO records"


def test_create_decision_missing_user(client, decision_brief_payload):
    headers = {"X-Tenant": "tenant_alpha"}
    res = client.post("/v1/decisions", json=decision_brief_payload, headers=headers)
    assert res.status_code == 401


def test_create_decision_invalid_user(client, decision_brief_payload):
    headers = {"X-Tenant": "tenant_alpha", "X-User": "invalid_user"}
    res = client.post("/v1/decisions", json=decision_brief_payload, headers=headers)
    assert res.status_code == 401


# ============================================================================
# 3. GET /v1/decisions & GET /v1/decisions/{id}
# ============================================================================

def test_read_decisions_isolation_matrix(client, decision_brief_payload):
    # 1. Create a real decision in tenant_alpha by alpha.manager
    alpha_headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
    create_res = client.post("/v1/decisions", json=decision_brief_payload, headers=alpha_headers)
    assert create_res.status_code == 201
    decision_id = create_res.json()["id"]

    # 2. GET /v1/decisions
    # A. Valid tenant_alpha user sees it
    res_a = client.get("/v1/decisions", headers=alpha_headers)
    assert res_a.status_code == 200
    alpha_ids = [d["id"] for d in res_a.json()]
    assert decision_id in alpha_ids

    # B. User claiming tenant_beta cannot see it in list
    beta_header_cross = {"X-Tenant": "tenant_beta", "X-User": "alpha.manager"}
    res_b = client.get("/v1/decisions", headers=beta_header_cross)
    assert res_b.status_code == 404

    # C. Cross user claiming tenant_alpha cannot list
    alpha_header_cross = {"X-Tenant": "tenant_alpha", "X-User": "beta.manager"}
    res_c = client.get("/v1/decisions", headers=alpha_header_cross)
    assert res_c.status_code == 404

    # D & E. Missing & invalid user -> 401
    assert client.get("/v1/decisions", headers={"X-Tenant": "tenant_alpha"}).status_code == 401
    assert client.get("/v1/decisions", headers={"X-Tenant": "tenant_alpha", "X-User": "fake"}).status_code == 401

    # 3. GET /v1/decisions/{id}
    # A. Valid user reads decision
    res_get_a = client.get(f"/v1/decisions/{decision_id}", headers=alpha_headers)
    assert res_get_a.status_code == 200
    assert res_get_a.json()["id"] == decision_id

    # B. Cross-tenant user (alpha.manager under tenant_beta) -> 404
    res_get_b = client.get(f"/v1/decisions/{decision_id}", headers=beta_header_cross)
    assert res_get_b.status_code == 404
    assert res_get_b.json() == {"detail": "not found"}

    # C. Cross-tenant user (beta.manager under tenant_alpha) -> 404
    res_get_c = client.get(f"/v1/decisions/{decision_id}", headers=alpha_header_cross)
    assert res_get_c.status_code == 404
    assert res_get_c.json() == {"detail": "not found"}

    # D & E -> 401
    assert client.get(f"/v1/decisions/{decision_id}", headers={"X-Tenant": "tenant_alpha"}).status_code == 401
    assert client.get(f"/v1/decisions/{decision_id}", headers={"X-Tenant": "tenant_alpha", "X-User": "fake"}).status_code == 401


# ============================================================================
# 4. POST /v1/decisions/{id}/transition
# ============================================================================

def test_transition_decision_isolation_and_state_unchanged(client, decision_brief_payload):
    # 1. Create a decision in tenant_alpha
    alpha_headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
    create_res = client.post("/v1/decisions", json=decision_brief_payload, headers=alpha_headers)
    assert create_res.status_code == 201
    decision_id = create_res.json()["id"]

    # 2. Attempt cross-tenant transition (alpha.manager pretending tenant_beta)
    cross_b = {"X-Tenant": "tenant_beta", "X-User": "alpha.manager"}
    res_b = client.post(f"/v1/decisions/{decision_id}/transition", json={"status": "proposed", "reason": "test"}, headers=cross_b)
    assert res_b.status_code == 404

    # Attempt cross-tenant transition (beta.manager pretending tenant_alpha)
    cross_c = {"X-Tenant": "tenant_alpha", "X-User": "beta.manager"}
    res_c = client.post(f"/v1/decisions/{decision_id}/transition", json={"status": "proposed", "reason": "test"}, headers=cross_c)
    assert res_c.status_code == 404

    # 3. Verify status remains unchanged ('draft')
    get_res = client.get(f"/v1/decisions/{decision_id}", headers=alpha_headers)
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "draft", "Persisted decision status must remain unchanged after denied transition"

    # 4. Valid transition by alpha.manager -> succeeds
    valid_res = client.post(f"/v1/decisions/{decision_id}/transition", json={"status": "proposed", "reason": "test"}, headers=alpha_headers)
    assert valid_res.status_code == 200
    assert valid_res.json()["status"] == "proposed"


# ============================================================================
# 5. POST /v1/decisions/{id}/outcome
# ============================================================================

def test_outcome_decision_isolation_and_state_unchanged(client, decision_brief_payload):
    # 1. Create decision in tenant_alpha
    alpha_headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
    create_res = client.post("/v1/decisions", json=decision_brief_payload, headers=alpha_headers)
    assert create_res.status_code == 201
    decision_id = create_res.json()["id"]

    outcome_payload = {
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

    # 2. Attempt cross-tenant outcome write (alpha.manager under tenant_beta) -> 404
    cross_b = {"X-Tenant": "tenant_beta", "X-User": "alpha.manager"}
    res_b = client.post(f"/v1/decisions/{decision_id}/outcome", json=outcome_payload, headers=cross_b)
    assert res_b.status_code == 404

    # Attempt cross-tenant outcome write (beta.manager under tenant_alpha) -> 404
    cross_c = {"X-Tenant": "tenant_alpha", "X-User": "beta.manager"}
    res_c = client.post(f"/v1/decisions/{decision_id}/outcome", json=outcome_payload, headers=cross_c)
    assert res_c.status_code == 404

    # 3. Verify outcome remains empty / unchanged
    get_res = client.get(f"/v1/decisions/{decision_id}", headers=alpha_headers)
    assert get_res.status_code == 200
    assert get_res.json().get("outcome") is None, "Outcome must remain unchanged after denied mutation"

    # 4. Valid outcome write by alpha.manager -> succeeds
    valid_res = client.post(f"/v1/decisions/{decision_id}/outcome", json=outcome_payload, headers=alpha_headers)
    assert valid_res.status_code == 200
    assert valid_res.json()["outcome"]["review_verdict"] == "supported_improvement"
