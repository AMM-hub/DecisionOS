"""Tests for bounded list endpoints and pagination (R3)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from decisionos_analytics.register import DecisionBrief, create_decision
from decisionos_analytics.store import Store


@pytest.fixture
def app_store(client: TestClient, tmp_path):
    return Store(tmp_path / "data" / "control.sqlite3")


@pytest.fixture
def seeded_client_with_65_decisions(client: TestClient, app_store, alpha_headers):
    """Seed 65 decisions into tenant_alpha."""
    tenant = "tenant_alpha"
    brief = DecisionBrief(
        problem="Test backlog overflow",
        relevant_findings=["Queue length exceeded limit"],
        proposed_action="Scale worker capacity",
        baseline_option="Do nothing",
        scope="Support operations",
        owner="alpha.manager",
        trade_offs="Increased cost vs lower latency",
        assumptions="Traffic remains steady",
        evidence_coverage="High",
        validation_plan="Measure throughput after 24h",
        counter_metrics=["Error rate"],
        expected_effect="50% reduction in queue wait time",
    )
    for i in range(65):
        create_decision(
            app_store.conn,
            tenant_id=tenant,
            title=f"Decision Test Item {i:03d}",
            brief=brief,
            created_by="alpha.manager",
        )
    return client


def test_default_cap_50_applied_with_x_total_count(seeded_client_with_65_decisions: TestClient, alpha_headers):
    client = seeded_client_with_65_decisions
    r = client.get("/v1/decisions", headers=alpha_headers)
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    assert len(items) == 50
    assert r.headers.get("x-total-count") == "65"


def test_limit_and_offset_respected(seeded_client_with_65_decisions: TestClient, alpha_headers):
    client = seeded_client_with_65_decisions
    r1 = client.get("/v1/decisions?limit=10&offset=0", headers=alpha_headers)
    assert r1.status_code == 200
    p1 = r1.json()
    assert len(p1) == 10
    assert r1.headers.get("x-total-count") == "65"

    r2 = client.get("/v1/decisions?limit=10&offset=10", headers=alpha_headers)
    assert r2.status_code == 200
    p2 = r2.json()
    assert len(p2) == 10
    assert r2.headers.get("x-total-count") == "65"

    # Disjoint slices
    p1_ids = {item["id"] for item in p1}
    p2_ids = {item["id"] for item in p2}
    assert p1_ids.isdisjoint(p2_ids)

    # Tail page
    r_tail = client.get("/v1/decisions?limit=20&offset=50", headers=alpha_headers)
    assert r_tail.status_code == 200
    p_tail = r_tail.json()
    assert len(p_tail) == 15
    assert r_tail.headers.get("x-total-count") == "65"


def test_combined_limit_offset_disjoint_slices_complete(seeded_client_with_65_decisions: TestClient, alpha_headers):
    client = seeded_client_with_65_decisions
    all_seen_ids = set()

    for offset in (0, 25, 50):
        r = client.get(f"/v1/decisions?limit=25&offset={offset}", headers=alpha_headers)
        assert r.status_code == 200
        items = r.json()
        current_ids = {item["id"] for item in items}
        assert all_seen_ids.isdisjoint(current_ids)
        all_seen_ids.update(current_ids)

    assert len(all_seen_ids) == 65


@pytest.mark.parametrize(
    "query_param,expected_detail_contains",
    [
        ("limit=0", "limit"),
        ("limit=501", "limit"),
        ("offset=-1", "offset"),
        ("limit=abc", "limit"),
    ],
)
def test_invalid_pagination_returns_422_flat_code(client: TestClient, alpha_headers, query_param, expected_detail_contains):
    r = client.get(f"/v1/decisions?{query_param}", headers=alpha_headers)
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "invalid_pagination"
    assert isinstance(body["detail"], str)
    assert expected_detail_contains in body["detail"].lower()
    assert body["status"] == 422


def test_q_substring_filter_decisions(client: TestClient, app_store, alpha_headers):
    tenant = "tenant_alpha"
    brief = DecisionBrief(
        problem="P", relevant_findings=[], proposed_action="A", baseline_option="B",
        scope="S", owner="alpha.manager", trade_offs="T", assumptions="A",
        evidence_coverage="C", validation_plan="V", counter_metrics=[], expected_effect="E",
    )
    create_decision(app_store.conn, tenant, "Emergency Server Outage Escalation", brief, "alpha.manager")
    create_decision(app_store.conn, tenant, "Routine Database Backup Policy", brief, "alpha.manager")

    # Lowercase match
    r1 = client.get("/v1/decisions?q=emergency", headers=alpha_headers)
    assert r1.status_code == 200
    items1 = r1.json()
    assert len(items1) == 1
    assert "Emergency" in items1[0]["title"]
    assert r1.headers.get("x-total-count") == "1"

    # Uppercase match (case-insensitive)
    r2 = client.get("/v1/decisions?q=EMERGENCY", headers=alpha_headers)
    assert r2.status_code == 200
    assert len(r2.json()) == 1

    # Substring match
    r3 = client.get("/v1/decisions?q=database", headers=alpha_headers)
    assert r3.status_code == 200
    items3 = r3.json()
    assert len(items3) == 1
    assert "Routine Database" in items3[0]["title"]

    # Miss
    r4 = client.get("/v1/decisions?q=nonexistent_xyz", headers=alpha_headers)
    assert r4.status_code == 200
    assert r4.json() == []
    assert r4.headers.get("x-total-count") == "0"


def test_q_substring_filter_datasets(client: TestClient, app_store, alpha_headers):
    """The q filter must narrow by name substring. Uses a unique token so the
    assertion is independent of datasets seeded by other tests in this module."""
    import uuid
    tenant = "tenant_alpha"
    token = uuid.uuid4().hex[:8]
    wanted = f"Telecom Churn Rates {token}"
    other = f"Retail Billing Claims {token}"
    with app_store.conn:
        app_store.conn.execute(
            "INSERT INTO dataset (tenant_id, id, workspace_id, name, created_at) VALUES (?, ?, ?, ?, ?)",
            (tenant, f"ds-custom-telecom-{token}", "ws-support-ops", wanted, "2026-01-01T00:00:00Z"),
        )
        app_store.conn.execute(
            "INSERT INTO dataset (tenant_id, id, workspace_id, name, created_at) VALUES (?, ?, ?, ?, ?)",
            (tenant, f"ds-custom-billing-{token}", "ws-support-ops", other, "2026-01-01T00:00:00Z"),
        )

    r = client.get(f"/v1/datasets?q=churn%20rates%20{token}", headers=alpha_headers)
    assert r.status_code == 200
    names = [i["name"] for i in r.json()]
    assert names == [wanted], names
    assert r.headers.get("x-total-count") == "1"

    # the sibling row must not match
    r2 = client.get(f"/v1/datasets?q=billing%20claims%20{token}", headers=alpha_headers)
    assert [i["name"] for i in r2.json()] == [other]


def test_q_substring_filter_investigations(client: TestClient, app_store, alpha_headers):
    from decisionos_analytics.investigations import create_investigation, SourceType
    tenant = "tenant_alpha"
    create_investigation(
        app_store, tenant,
        title="Spike in Fiber Disconnections",
        question="Why did fiber disconnects spike in March?",
        owner="alpha.manager",
        user_id="alpha.manager",
        source_type=SourceType.MONITORING_EPISODE,
    )
    create_investigation(
        app_store, tenant,
        title="Latency Increase in Payment Gateway",
        question="What caused payment gateway latency?",
        owner="alpha.manager",
        user_id="alpha.manager",
        source_type=SourceType.AD_HOC,
    )

    r = client.get("/v1/investigations?q=fiber", headers=alpha_headers)
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert "Fiber Disconnections" in items[0]["title"]
    assert r.headers.get("x-total-count") == "1"

    r_upper = client.get("/v1/investigations?q=FIBER", headers=alpha_headers)
    assert r_upper.status_code == 200
    assert len(r_upper.json()) == 1


def test_pagination_on_pilots_and_models(client: TestClient, app_store, alpha_headers):
    # Pilots
    r_pilots = client.get("/v1/pilots?limit=10&offset=0", headers=alpha_headers)
    assert r_pilots.status_code == 200
    assert isinstance(r_pilots.json(), list)
    assert "x-total-count" in r_pilots.headers

    # Models
    r_models = client.get("/v1/predictive/models?limit=10&offset=0", headers=alpha_headers)
    assert r_models.status_code == 200
    assert isinstance(r_models.json(), list)
    assert "x-total-count" in r_models.headers

    # Outbox
    r_outbox = client.get("/v1/jobs/outbox?limit=10&offset=0", headers=alpha_headers)
    assert r_outbox.status_code == 200
    assert isinstance(r_outbox.json(), list)
    assert "x-total-count" in r_outbox.headers
