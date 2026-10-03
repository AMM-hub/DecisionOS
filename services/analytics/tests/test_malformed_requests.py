"""DOS-QA-010 Malformed Requests Regression Test Suite.

Verifies that malformed client input (bad JSON syntax, wrong content-type,
missing fields) returns appropriate 400/422 status codes without raising
unhandled HTTP 500 exceptions or exposing Python internal tracebacks.
"""

from __future__ import annotations

import pytest


def test_malformed_json_syntax(client):
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager", "Content-Type": "application/json"}
    # Bad JSON syntax
    res = client.post("/v1/scenarios/solve", content="{invalid_json:", headers=headers)
    assert res.status_code == 400
    data = res.json()
    assert "code" in data
    assert data["code"] in ("malformed_json", "malformed_request")


def test_wrong_content_type_non_json(client):
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager", "Content-Type": "text/plain"}
    res = client.post("/v1/scenarios/solve", content="not json content at all", headers=headers)
    assert res.status_code in (400, 415, 422)


def test_empty_json_body(client):
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager", "Content-Type": "application/json"}
    res = client.post("/v1/scenarios/solve", content="", headers=headers)
    assert res.status_code in (400, 422)


def test_valid_json_invalid_schema(client):
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager", "Content-Type": "application/json"}
    # Valid JSON, missing required fields like "groups", "queues"
    res = client.post("/v1/scenarios/solve", json={"foo": "bar"}, headers=headers)
    assert res.status_code == 422
    assert "invalid_inputs" in res.text or "detail" in res.json()


def test_valid_request(client):
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
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
    res = client.post("/v1/scenarios/solve", json=payload, headers=headers)
    assert res.status_code == 200
    assert "status" in res.json()
