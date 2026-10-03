"""DOS-QA-004 Solver Error Classification Test Suite.

Verifies classification of solver outcomes:
- Feasible model -> 200 with status 'optimal'/'feasible_time_limited'
- Infeasible model -> 200 with domain status 'infeasible'
- Malformed scenario -> 422 with invalid_inputs
- Unexpected internal exception -> 500 safe error body (zero leaked tracebacks)
"""

from __future__ import annotations

from unittest.mock import patch
import pytest


@pytest.fixture
def base_headers():
    return {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}


def test_feasible_model_returns_200_optimal(client, base_headers):
    payload = {
        "template": "reallocate-capacity",
        "groups": ["G1"],
        "queues": ["Q1"],
        "periods": [1],
        "segments": [1],
        "eligibility": {"G1,Q1": True},
        "regular_hours": {"G1,1": 160.0},
        "overtime_cap": {"G1,1": 40.0},
        "arrivals": {"Q1,1": 50.0},
        "opening_backlog": {"Q1": 0.0},
        "segment_width": {"G1,Q1,1,1": 160.0},
        "marginal_rate": {"G1,Q1,1,1": 1.0},
        "regular_cost": {"G1,1": 10.0},
        "overtime_cost": {"G1,1": 15.0},
        "backlog_penalty": {"Q1,1": 5.0},
    }
    res = client.post("/v1/scenarios/solve", json=payload, headers=base_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("optimal", "feasible_time_limited")
    assert "objective" in data


def test_infeasible_model_returns_200_infeasible_status(client, base_headers):
    from decisionos_analytics.optimization import AllocationSolution

    infeasible_solution = AllocationSolution(
        status="infeasible",
        objective=None,
        bound=None,
        gap=None,
        solver="PULP_CBC_CMD",
        solver_version="2.10.10",
        runtime=0.012,
        variables={},
        constraints={},
        infeasibility_report={"method": "IIS", "conflict_constraints": ["Capacity_G1_1"]},
    )

    with patch("decisionos_analytics.optimization.solve_allocation", return_value=infeasible_solution):
        payload = {
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
        res = client.post("/v1/scenarios/solve", json=payload, headers=base_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "infeasible"
        assert "infeasibility_report" in data
        assert data["infeasibility_report"]["method"] == "IIS"


def test_malformed_scenario_inputs_returns_422(client, base_headers):
    payload = {
        "groups": ["G1"],
        # Missing queues field
    }
    res = client.post("/v1/scenarios/solve", json=payload, headers=base_headers)
    assert res.status_code == 422
    assert "invalid_inputs" in res.text


def test_unexpected_internal_exception_returns_500_safe_error(client, base_headers):
    payload = {
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

    # Simulate an unexpected internal system crash (e.g., RuntimeError / internal library bug)
    with patch("decisionos_analytics.optimization.solve_allocation", side_effect=RuntimeError("Internal system bug! Secret database path /var/secret")):
        res = client.post("/v1/scenarios/solve", json=payload, headers=base_headers)
        assert res.status_code == 500
        assert "Internal system bug" not in res.text, "Raw exception message must not be leaked to client"
        assert "/var/secret" not in res.text, "Internal path/stack details must not be leaked"
        data = res.json()
        assert data["code"] == "solver_internal_error"
        assert data["detail"] == "The optimization request could not be completed."
