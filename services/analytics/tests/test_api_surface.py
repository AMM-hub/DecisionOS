"""Regression coverage for the frontend-facing API surface: the published-dataset
row_count path (sqlite3.Row has no .get()), plus the health, uploads-list,
schema, and withdraw endpoints the Nuxt SPA depends on."""

from __future__ import annotations

from conftest import FIXTURES, upload_and_finalize

WINDOW = {"start": "2026-01-01T00:00:00Z", "end": "2026-04-01T00:00:00Z", "timezone": "Asia/Bahrain"}


def _publish_tickets(client, headers):
    uid, fin = upload_and_finalize(client, headers, FIXTURES / "tenant_alpha" / "tickets_cases.csv")
    client.post(f"/v1/datasets/{fin['dataset_id']}/grain-confirmation", json={"key_columns": ["case_id"]}, headers=headers)
    r = client.post(f"/v1/datasets/{fin['dataset_id']}/revisions/{fin['revision']}/publish", headers=headers)
    assert r.status_code == 200, r.text
    return fin["dataset_id"], fin["revision"]


def test_health_is_public(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_datasets_list_reports_published_row_count(client, alpha_headers):
    """Regression: .get() on sqlite3.Row raised AttributeError once a revision was published."""
    ds_id, rev = _publish_tickets(client, alpha_headers)
    r = client.get("/v1/datasets", headers=alpha_headers)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    d = rows[0]
    assert d["dataset_id"] == ds_id
    assert d["revision"] == rev
    assert d["grain_confirmed"] is True
    assert d["row_count"] == 420  # golden count from manifest
    assert d["latest_revision"] == rev
    assert d["latest_revision_state"] == "published"


def test_uploads_list_and_schema(client, alpha_headers):
    ds_id, rev = _publish_tickets(client, alpha_headers)
    ups = client.get("/v1/uploads", headers=alpha_headers).json()
    assert len(ups) == 1
    assert ups[0]["dataset_id"] == ds_id
    assert ups[0]["status"] == "parsed"
    schema = client.get(f"/v1/datasets/{ds_id}/schema", headers=alpha_headers).json()
    assert schema["revision"] == rev
    assert schema["columns"]["case_id"] == "string"
    assert "created_at" in schema["columns"]


def test_withdraw_blocks_queries_and_reapproval_restores(client, alpha_headers, modeler_headers):
    ds_id, _ = _publish_tickets(client, alpha_headers)
    metric = {
        "metric_id": "metric-open-count", "name": "Open count", "kind": "count", "dataset_id": ds_id,
        "time_basis": "created_at", "timezone": "Asia/Bahrain",
        "eligibility": [{"op": "eq", "field": "status", "value": "open"}],
        "expression": {"kind": "count", "predicates": []},
    }
    assert client.post("/v1/metrics/definitions", json=metric, headers=modeler_headers).status_code == 201
    assert client.post("/v1/metrics/definitions/metric-open-count/approve",
                       json={"version": 1, "change_reason": "reviewed"}, headers=alpha_headers).status_code == 200
    ok = client.post("/v1/metrics/query", json={"schema_version": "1.0", "metric_id": "metric-open-count", "window": WINDOW}, headers=alpha_headers).json()
    assert ok["status"] == "answered"

    w = client.post("/v1/metrics/definitions/metric-open-count/withdraw", json={"change_reason": "retired"}, headers=alpha_headers)
    assert w.status_code == 200 and w.json()["status"] == "withdrawn"

    refused = client.post("/v1/metrics/query", json={"schema_version": "1.0", "metric_id": "metric-open-count", "window": WINDOW}, headers=alpha_headers).json()
    assert refused["status"] == "insufficient_data" and refused["reason_code"] == "metric_not_certified"

    listed = client.get("/v1/metrics/definitions", headers=alpha_headers).json()
    assert [d["status"] for d in listed] == ["withdrawn"]

    # re-approval restores certification
    assert client.post("/v1/metrics/definitions/metric-open-count/approve",
                       json={"version": 1, "change_reason": "re-reviewed"}, headers=alpha_headers).status_code == 200
    again = client.post("/v1/metrics/query", json={"schema_version": "1.0", "metric_id": "metric-open-count", "window": WINDOW}, headers=alpha_headers).json()
    assert again["status"] == "answered"


def test_withdraw_requires_active_publication(client, alpha_headers, modeler_headers):
    ds_id, _ = _publish_tickets(client, alpha_headers)
    metric = {
        "metric_id": "metric-never-approved", "name": "Nope", "kind": "count", "dataset_id": ds_id,
        "time_basis": "created_at", "timezone": "Asia/Bahrain", "eligibility": [],
        "expression": {"kind": "count", "predicates": []},
    }
    client.post("/v1/metrics/definitions", json=metric, headers=modeler_headers)
    r = client.post("/v1/metrics/definitions/metric-never-approved/withdraw", json={"change_reason": "x"}, headers=alpha_headers)
    assert r.status_code == 409
