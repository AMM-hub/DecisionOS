"""WP-00 Pilot Contract, Data Readiness Gate & Security Tests."""

from __future__ import annotations

import io
import json
import pytest
import polars as pl
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app
from decisionos_analytics.pilot import (
    PilotStatus,
    create_pilot,
    get_pilot,
    list_pilots,
    update_pilot_status,
    validate_pilot_data_readiness,
)


@pytest.fixture
def pilot_app(tmp_path):
    data_dir = tmp_path / "data"
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    store = app.state.store
    objects = app.state.objects
    return client, store, objects


def test_pilot_contract_persistence_and_lifecycle(pilot_app):
    _, store, _ = pilot_app
    tenant = "tenant_alpha"

    # 1. Create Pilot
    plt = create_pilot(store, tenant, "Support SLA Pilot", "alpha.manager", domain="support_ticket_operations")
    assert plt["id"].startswith("plt-")
    assert plt["status"] == "draft"
    assert plt["domain"] == "support_ticket_operations"

    # 2. Get & List
    fetched = get_pilot(store, tenant, plt["id"])
    assert fetched is not None
    assert fetched["name"] == "Support SLA Pilot"

    all_pilots = list_pilots(store, tenant)
    assert len(all_pilots) >= 1

    # 3. Lifecycle state machine: draft -> configuration -> ready_for_evaluation -> active
    p1 = update_pilot_status(store, tenant, plt["id"], PilotStatus.CONFIGURATION, "alpha.manager")
    assert p1["status"] == "configuration"

    p2 = update_pilot_status(store, tenant, plt["id"], PilotStatus.READY_FOR_EVALUATION, "alpha.manager")
    assert p2["status"] == "ready_for_evaluation"

    p3 = update_pilot_status(store, tenant, plt["id"], PilotStatus.ACTIVE, "alpha.manager")
    assert p3["status"] == "active"

    # 4. Invalid reverse transition -> ValueError
    with pytest.raises(ValueError, match="Invalid pilot status transition"):
        update_pilot_status(store, tenant, plt["id"], PilotStatus.DRAFT, "alpha.manager")


def test_validate_pilot_data_readiness():
    # 1. Empty dataframe -> BLOCKED
    df_empty = pl.DataFrame()
    res_empty = validate_pilot_data_readiness(df_empty)
    assert res_empty["status"] == "BLOCKED"

    # 2. Missing required columns -> BLOCKED
    df_bad = pl.DataFrame({"some_col": [1, 2, 3]})
    res_bad = validate_pilot_data_readiness(df_bad)
    assert res_bad["status"] == "BLOCKED"
    assert any("Missing required" in r for r in res_bad["reasons"])

    # 3. Good dataset -> PASS
    df_good = pl.DataFrame({
        "ticket_id": ["T1", "T2"],
        "timestamp": ["2026-10-01T10:00:00Z", "2026-10-01T11:00:00Z"],
        "status": ["open", "closed"],
        "sla_deadline": ["2026-10-02T10:00:00Z", "2026-10-02T11:00:00Z"],
        "queue": ["Tier1", "Tier2"],
    })
    res_good = validate_pilot_data_readiness(df_good)
    assert res_good["status"] == "PASS"
    assert res_good["metrics"]["unique_cases"] == 2


def test_pilot_rest_api_and_tenant_security(pilot_app):
    client, store, objects = pilot_app
    alpha_mgr = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
    beta_mgr = {"X-Tenant": "tenant_beta", "X-User": "beta.manager"}

    # 1. Create Pilot via API
    res = client.post("/v1/pilots", headers=alpha_mgr, json={
        "name": "Alpha Customer Pilot",
        "domain": "support_ticket_operations",
        "owner": "alpha.manager"
    })
    assert res.status_code == 201
    plt = res.json()
    plt_id = plt["id"]

    # 2. List Pilots
    list_res = client.get("/v1/pilots", headers=alpha_mgr)
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1

    # 3. Cross-Tenant Access -> 404 (non-disclosing)
    assert client.get(f"/v1/pilots/{plt_id}", headers=beta_mgr).status_code == 404
    assert client.post(f"/v1/pilots/{plt_id}/status", headers=beta_mgr, json={"status": "active"}).status_code == 404

    # 4. Status Transition via API: draft -> configuration
    st_res = client.post(f"/v1/pilots/{plt_id}/status", headers=alpha_mgr, json={"status": "configuration"})
    assert st_res.status_code == 200
    assert st_res.json()["status"] == "configuration"

    # 5. Semantic Pack Endpoint
    sem_res = client.get("/v1/pilots/semantic-pack", headers=alpha_mgr)
    assert sem_res.status_code == 200
    assert "semantic_pack" in sem_res.json()
    assert len(sem_res.json()["semantic_pack"]) >= 5

    # 6. Pilot Summary Endpoint
    sum_res = client.get(f"/v1/pilots/{plt_id}/summary", headers=alpha_mgr)
    assert sum_res.status_code == 200
    summary = sum_res.json()["summary"]
    assert summary["auth_security_gate"] == "INTERNAL_EVALUATION_ONLY"
