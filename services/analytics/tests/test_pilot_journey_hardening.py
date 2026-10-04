"""Unit and integration tests for WP-03 Operational Journey Hardening & Bad Data Gates."""

import io
import json
import pytest
import polars as pl
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app
from decisionos_analytics.pilot import create_pilot, validate_pilot_data_readiness, get_pilot


@pytest.fixture
def pilot_ctx(tmp_path):
    data_dir = tmp_path / "data"
    app = create_app(data_dir=data_dir)
    client = TestClient(app)
    store = app.state.store
    objects = app.state.objects
    return app, client, store, objects


def test_data_quality_gate_out_of_order_events():
    # Events where second event timestamp is BEFORE first event timestamp
    df = pl.DataFrame({
        "ticket_id": ["T101", "T101"],
        "timestamp": ["2026-10-01T12:00:00Z", "2026-10-01T10:00:00Z"],
        "status": ["created", "in_progress"],
    })
    res = validate_pilot_data_readiness(df, case_col="ticket_id", timestamp_col="timestamp", status_col="status")
    assert res["status"] == "BLOCKED"
    assert any("Invalid event ordering" in r for r in res["reasons"])


def test_data_quality_gate_completion_before_creation():
    df = pl.DataFrame({
        "ticket_id": ["T201", "T201"],
        "timestamp": ["2026-10-01T08:00:00Z", "2026-10-01T10:00:00Z"],
        "status": ["completed", "created"],
    })
    res = validate_pilot_data_readiness(df, case_col="ticket_id", timestamp_col="timestamp", status_col="status")
    assert res["status"] == "BLOCKED"
    assert any("Completion before creation" in r for r in res["reasons"])


def test_refresh_failure_preserves_previous_revision(pilot_ctx):
    app, client, store, objects = pilot_ctx
    tenant = "tenant_alpha"
    user = "alpha.manager"
    headers = {"X-Tenant": tenant, "X-User": user}

    # 1. Upload valid dataset rev 1
    df1 = pl.DataFrame({
        "ticket_id": ["T1", "T2"],
        "timestamp": ["2026-10-01T10:00:00Z", "2026-10-01T11:00:00Z"],
        "status": ["open", "closed"],
    })
    buf1 = io.BytesIO()
    df1.write_parquet(buf1)
    bytes1 = buf1.getvalue()

    dataset_id = "ds_support_ops"
    obj_res = objects.put_revision_object(tenant, dataset_id, 1, "rev1.parquet", bytes1)
    manifest1 = {"objects": [{"key": obj_res["key"]}]}

    store.conn.execute(
        "INSERT INTO dataset (tenant_id, id, workspace_id, name, published_revision, created_at) VALUES (?, ?, 'ws-support-ops', 'Support Data', 1, '2026-10-01T00:00:00Z')",
        (tenant, dataset_id)
    )
    store.conn.execute(
        "INSERT INTO dataset_revision (tenant_id, dataset_id, revision, state, manifest, row_count, created_at) VALUES (?, ?, 1, 'published', ?, 2, '2026-10-01T00:00:00Z')",
        (tenant, dataset_id, json.dumps(manifest1))
    )
    store.conn.commit()

    # 2. Create Pilot bound to dataset rev 1
    p = create_pilot(store, tenant, "Hardening Test Pilot", user, dataset_id=dataset_id, dataset_revision=1)
    pilot_id = p["id"]

    # 3. Attempt refresh with invalid request body -> 422
    bad_ref = client.post(f"/v1/pilots/{pilot_id}/refresh", headers=headers, json={"invalid_field": "no_content"})
    assert bad_ref.status_code == 422

    # 4. Verify original pilot state and revision remain untouched (revision = 1)
    current_pilot = get_pilot(store, tenant, pilot_id)
    assert current_pilot["dataset_revision"] == 1

    # 5. Successful refresh creates revision 2 cleanly
    df2 = pl.DataFrame({
        "ticket_id": ["T1", "T2", "T3"],
        "timestamp": ["2026-10-01T10:00:00Z", "2026-10-01T11:00:00Z", "2026-10-01T12:00:00Z"],
        "status": ["open", "closed", "open"],
    })
    buf2 = io.BytesIO()
    df2.write_parquet(buf2)
    csv_str = "ticket_id,timestamp,status\nT1,2026-10-01T10:00:00Z,open\nT2,2026-10-01T11:00:00Z,closed\nT3,2026-10-01T12:00:00Z,open"

    good_ref = client.post(f"/v1/pilots/{pilot_id}/refresh", headers=headers, json={"csv_content": csv_str})
    assert good_ref.status_code == 200
    refreshed_pilot = good_ref.json()
    assert refreshed_pilot["dataset_revision"] == 2
