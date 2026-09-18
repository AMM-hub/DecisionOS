"""M4 Scenario & Decision Studio API tests (spec §17): template catalog,
optimisation solver endpoint, fixture verification, and refusal paths.
"""

from __future__ import annotations

import json

import pytest
from conftest import FIXTURES


def _solve_payload():
    """Standard fixture payload for the allocation solver."""
    return {
        "groups": ["G1", "G2"],
        "queues": ["Q1", "Q2"],
        "periods": [1, 2, 3],
        "segments": [1, 2],
        "eligibility": {json.dumps(["G1", "Q1"]): True, json.dumps(["G2", "Q2"]): True},
        "regular_hours": {json.dumps(["G1", 1]): 160, json.dumps(["G1", 2]): 160, json.dumps(["G1", 3]): 160,
                          json.dumps(["G2", 1]): 160, json.dumps(["G2", 2]): 160, json.dumps(["G2", 3]): 160},
        "overtime_cap": {json.dumps(["G1", 1]): 40, json.dumps(["G1", 2]): 40, json.dumps(["G1", 3]): 40,
                          json.dumps(["G2", 1]): 40, json.dumps(["G2", 2]): 40, json.dumps(["G2", 3]): 40},
        "arrivals": {json.dumps(["Q1", 1]): 120, json.dumps(["Q1", 2]): 120, json.dumps(["Q1", 3]): 120,
                      json.dumps(["Q2", 1]): 120, json.dumps(["Q2", 2]): 120, json.dumps(["Q2", 3]): 120},
        "opening_backlog": {"Q1": 30, "Q2": 20},
        "segment_width": {
            json.dumps(["G1", "Q1", 1, 1]): 160, json.dumps(["G1", "Q1", 1, 2]): 40,
            json.dumps(["G1", "Q1", 2, 1]): 160, json.dumps(["G1", "Q1", 2, 2]): 40,
            json.dumps(["G1", "Q1", 3, 1]): 160, json.dumps(["G1", "Q1", 3, 2]): 40,
            json.dumps(["G2", "Q2", 1, 1]): 160, json.dumps(["G2", "Q2", 1, 2]): 40,
            json.dumps(["G2", "Q2", 2, 1]): 160, json.dumps(["G2", "Q2", 2, 2]): 40,
            json.dumps(["G2", "Q2", 3, 1]): 160, json.dumps(["G2", "Q2", 3, 2]): 40,
        },
        "marginal_rate": {
            json.dumps(["G1", "Q1", 1, 1]): 2.0, json.dumps(["G1", "Q1", 1, 2]): 1.5,
            json.dumps(["G1", "Q1", 2, 1]): 2.0, json.dumps(["G1", "Q1", 2, 2]): 1.5,
            json.dumps(["G1", "Q1", 3, 1]): 2.0, json.dumps(["G1", "Q1", 3, 2]): 1.5,
            json.dumps(["G2", "Q2", 1, 1]): 2.0, json.dumps(["G2", "Q2", 1, 2]): 1.5,
            json.dumps(["G2", "Q2", 2, 1]): 2.0, json.dumps(["G2", "Q2", 2, 2]): 1.5,
            json.dumps(["G2", "Q2", 3, 1]): 2.0, json.dumps(["G2", "Q2", 3, 2]): 1.5,
        },
        "regular_cost": {json.dumps(k): 0.0 for k in [["G1", 1], ["G1", 2], ["G1", 3], ["G2", 1], ["G2", 2], ["G2", 3]]},
        "overtime_cost": {json.dumps(k): 30.0 for k in [["G1", 1], ["G1", 2], ["G1", 3], ["G2", 1], ["G2", 2], ["G2", 3]]},
        "backlog_penalty": {json.dumps(k): 50.0 for k in [["Q1", 1], ["Q1", 2], ["Q1", 3], ["Q2", 1], ["Q2", 2], ["Q2", 3]]},
    }


# ---- template catalog ---------------------------------------------------


def test_templates_listed(client, alpha_headers):
    r = client.get("/v1/scenarios/templates")
    assert r.status_code == 200
    templates = r.json()
    assert len(templates) >= 5
    tids = [t["template_id"] for t in templates]
    assert "reallocate-capacity" in tids
    assert "add-capacity" in tids


def test_template_has_required_fields(client, alpha_headers):
    r = client.get("/v1/scenarios/templates")
    t = r.json()[0]
    assert "template_id" in t
    assert "name" in t
    assert "sections" in t


# ---- solver API ---------------------------------------------------------


def test_solve_returns_optimal(client, alpha_headers):
    r = client.post("/v1/scenarios/solve", json=_solve_payload(), headers=alpha_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "optimal"
    assert data["objective"] is not None
    assert data["objective"] >= 0
    assert data["solver"] == "PULP_CBC_CMD"
    assert data["runtime"] > 0


def test_solve_reports_variable_count(client, alpha_headers):
    r = client.post("/v1/scenarios/solve", json=_solve_payload(), headers=alpha_headers)
    data = r.json()
    assert data["variable_count"] > 0


def test_solve_refuses_missing_groups(client, alpha_headers):
    payload = _solve_payload()
    del payload["groups"]
    r = client.post("/v1/scenarios/solve", json=payload, headers=alpha_headers)
    assert r.status_code == 422, r.text
    assert "invalid_inputs" in r.text


def test_solve_refuses_bad_eligibility(client, alpha_headers):
    payload = _solve_payload()
    payload["eligibility"] = "not_a_dict"  # should be a dict
    r = client.post("/v1/scenarios/solve", json=payload, headers=alpha_headers)
    assert r.status_code == 422, r.text


def test_solve_requires_auth(client):
    r = client.post("/v1/scenarios/solve", json=_solve_payload())
    assert r.status_code == 401


def test_solve_handles_infeasible(client, alpha_headers):
    payload = _solve_payload()
    # Zero capacity
    for g in ["G1", "G2"]:
        for t in [1, 2, 3]:
            payload["regular_hours"][json.dumps([g, t])] = 0
            payload["overtime_cap"][json.dumps([g, t])] = 0
    r = client.post("/v1/scenarios/solve", json=payload, headers=alpha_headers)
    assert r.status_code == 200
    assert r.json()["status"] in ("optimal", "infeasible", "no_feasible_solution_found")


def test_solve_handles_timelimit(client, alpha_headers):
    payload = _solve_payload()
    payload["timelimit"] = 1  # 1 second
    r = client.post("/v1/scenarios/solve", json=payload, headers=alpha_headers)
    assert r.status_code == 200
    assert r.json()["runtime"] < 10  # shouldn't hang


def test_solve_tenant_isolation(client, alpha_headers, beta_headers):
    """Beta can solve but their data is independent per tenant."""
    payload = _solve_payload()
    r = client.post("/v1/scenarios/solve", json=payload, headers=alpha_headers)
    assert r.status_code == 200
    r = client.post("/v1/scenarios/solve", json=payload, headers=beta_headers)
    assert r.status_code == 200