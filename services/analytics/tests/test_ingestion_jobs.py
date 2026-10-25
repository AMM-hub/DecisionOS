from __future__ import annotations

import json

from decisionos_analytics.connectors import ConnectorError
from decisionos_analytics.ingestion.jobs import execute_run, run_pending


class StubConnector:
    def __init__(self, header, rows, error: Exception | None = None) -> None:
        self.header = header
        self.rows = rows
        self.error = error
        self.calls = 0

    def read_rows(self, table, columns=None, limit=50_000, offset=0, watermark_column=None, watermark_value=None):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.header), [list(row) for row in self.rows]


def _rows(count: int = 12):
    return [
        [str(index), "north" if index % 2 else "south", index * 10]
        for index in range(1, count + 1)
    ]


def _source(store, tenant: str, source_id: str, name: str) -> None:
    store.conn.execute(
        """INSERT INTO data_source(
            tenant_id, id, name, kind, config_json, read_only, status, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?)""",
        (tenant, source_id, name, "stub", "{}", 1, "untested", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    store.conn.commit()


def _job(client, headers, source_id: str, name: str, **extra):
    body = {"data_source_id": source_id, "name": name, "target_table": "public.tickets", **extra}
    response = client.post("/v1/jobs", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_end_to_end_ingestion_publishes_queryable_dataset(client, alpha_headers, monkeypatch):
    store = client.app.state.store
    stub = StubConnector(["id", "region", "amount"], _rows(12))
    monkeypatch.setattr("decisionos_analytics.ingestion.jobs.get_connector", lambda row: stub)

    _source(store, "tenant_alpha", "src-stub-1", "Stub source")
    job = _job(client, alpha_headers, "src-stub-1", "Stub tickets job")

    enqueued = client.post(f"/v1/jobs/{job['id']}/run", headers=alpha_headers)
    assert enqueued.status_code == 202, enqueued.text
    run_id = enqueued.json()["run_id"]
    assert enqueued.json()["status"] == "queued"

    assert run_pending(store, 1) == 1
    runs = client.get(f"/v1/jobs/{job['id']}/runs", headers=alpha_headers).json()
    assert len(runs) == 1
    run = runs[0]
    assert run["id"] == run_id
    assert run["status"] == "succeeded"
    assert run["rows_read"] == 12
    assert run["rows_written"] == 12
    assert run["error"] is None
    assert run["dataset_id"]
    assert "read_ms" in run["stats"] and "publish_ms" in run["stats"]

    dataset_id = run["dataset_id"]
    datasets = client.get("/v1/datasets", headers=alpha_headers).json()
    dataset = next(item for item in datasets if item["dataset_id"] == dataset_id)
    assert dataset["revision"] is not None
    assert dataset["row_count"] == 12
    assert dataset["latest_revision_state"] == "published"

    query = client.post(
        f"/v1/datasets/{dataset_id}/query",
        json={"measures": [{"column": "*", "agg": "count"}], "limit": 10},
        headers=alpha_headers,
    )
    assert query.status_code == 200, query.text
    payload = query.json()
    expected = sum(1 for row in _rows(12))
    assert payload["rows"] == [[expected]]
    assert payload["evidence_ref"].startswith("ev-")

    # A run cannot execute twice, and an empty queue is a no-op.
    assert execute_run(store, run_id) is False
    assert run_pending(store, 1) == 0
    runs_after = client.get(f"/v1/jobs/{job['id']}/runs", headers=alpha_headers).json()
    assert len(runs_after) == 1
    assert stub.calls == 1


def test_failing_connector_marks_run_failed_and_keeps_watermark(client, alpha_headers, monkeypatch):
    store = client.app.state.store
    stub = StubConnector(
        ["id", "region", "amount"],
        [],
        error=ConnectorError("Source is unavailable."),
    )
    monkeypatch.setattr("decisionos_analytics.ingestion.jobs.get_connector", lambda row: stub)

    _source(store, "tenant_alpha", "src-stub-fail", "Failing source")
    job = _job(
        client,
        alpha_headers,
        "src-stub-fail",
        "Failing job",
        mode="incremental",
        watermark_column="id",
        watermark_value="5",
    )
    enqueued = client.post(f"/v1/jobs/{job['id']}/run", headers=alpha_headers)
    assert enqueued.status_code == 202

    assert run_pending(store, 1) == 1
    run = client.get(f"/v1/jobs/{job['id']}/runs", headers=alpha_headers).json()[0]
    assert run["status"] == "failed"
    assert run["error"] == "Source is unavailable."
    assert "Traceback" not in run["error"]

    current = client.get(f"/v1/jobs/{job['id']}", headers=alpha_headers).json()
    assert current["watermark_value"] == "5"
    assert current["latest_run"]["status"] == "failed"


def test_jobs_are_tenant_scoped(client, alpha_headers, beta_headers):
    store = client.app.state.store
    _source(store, "tenant_alpha", "src-tenant", "Tenant source")
    job = _job(client, alpha_headers, "src-tenant", "Tenant job")
    assert client.get(f"/v1/jobs/{job['id']}", headers=beta_headers).status_code == 404
    assert client.post(f"/v1/jobs/{job['id']}/run", headers=beta_headers).status_code == 404
    assert client.get("/v1/jobs", headers=beta_headers).json() == []
    assert json.loads(json.dumps(job))["id"] == job["id"]
