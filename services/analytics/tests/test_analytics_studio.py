"""P1b Analytics Studio: bounded dataset queries and saved analysis artifacts."""

from __future__ import annotations

import json

from conftest import FIXTURES, upload_and_finalize

COUNT_ROWS = {"column": "*", "agg": "count", "alias": "rows"}


def _publish(client, headers, filename: str = "tickets_cases.csv") -> tuple[str, int]:
    _uid, fin = upload_and_finalize(client, headers, FIXTURES / "tenant_alpha" / filename)
    dataset_id = fin["dataset_id"]
    client.post(
        f"/v1/datasets/{dataset_id}/grain-confirmation",
        json={"key_columns": ["case_id"]},
        headers=headers,
    )
    published = client.post(
        f"/v1/datasets/{dataset_id}/revisions/{fin['revision']}/publish", headers=headers
    )
    assert published.status_code == 200, published.text
    return dataset_id, fin["revision"]


def _body(dataset_id: str, **overrides):
    body = {
        "dataset_id": dataset_id,
        "revision": None,
        "dimensions": [],
        "measures": [COUNT_ROWS],
        "filters": [],
        "limit": 10,
    }
    body.update(overrides)
    return body


def _query(client, headers, dataset_id: str, **overrides):
    return client.post("/v1/analytics/query", json=_body(dataset_id, **overrides), headers=headers)


def test_scalar_aggregate_returns_one_real_row(client, alpha_headers):
    dataset_id, _revision = _publish(client, alpha_headers)
    response = _query(client, alpha_headers, dataset_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["row_count"] == 1
    assert body["truncated"] is False
    assert body["rows"] == [[420]]
    assert body["columns"] == [{"name": "rows", "type": "integer"}]
    assert body["evidence_ref"].startswith("ev-")

    store = client.app.state.store
    row = store.conn.execute(
        "SELECT payload FROM evidence WHERE tenant_id=? AND id=?", ("tenant_alpha", body["evidence_ref"])
    ).fetchone()
    assert row is not None
    payload = json.loads(row["payload"])
    assert payload["query"]["dataset_id"] == dataset_id
    assert payload["result_digest"]


def test_grouped_query_is_deterministic_and_ordered(client, alpha_headers):
    dataset_id, _revision = _publish(client, alpha_headers)
    first = _query(
        client, alpha_headers, dataset_id, dimensions=["originating_branch"], measures=[COUNT_ROWS]
    )
    assert first.status_code == 200, first.text
    rows = first.json()["rows"]
    assert len(rows) == 4
    assert [row[0] for row in rows] == sorted(row[0] for row in rows)
    assert sum(row[1] for row in rows) == 420

    second = _query(
        client, alpha_headers, dataset_id, dimensions=["originating_branch"], measures=[COUNT_ROWS]
    )
    assert second.json()["rows"] == rows


def test_unknown_column_and_unpublished_revision_are_rejected(client, alpha_headers):
    dataset_id, _revision = _publish(client, alpha_headers)
    unknown = _query(client, alpha_headers, dataset_id, measures=[{"column": "does_not_exist", "agg": "sum"}])
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "unknown_column"
    assert "does_not_exist" in unknown.json()["detail"]

    unknown_filter = _query(
        client,
        alpha_headers,
        dataset_id,
        filters=[{"column": "not_a_column", "op": "eq", "value": "x"}],
    )
    assert unknown_filter.status_code == 422
    assert unknown_filter.json()["code"] == "unknown_column"

    _uid, unpublished = upload_and_finalize(
        client,
        alpha_headers,
        FIXTURES / "tenant_alpha" / "tickets_cases.csv",
        filename="unpublished_tickets.csv",
    )
    staged = _query(client, alpha_headers, unpublished["dataset_id"], revision=1)
    assert staged.status_code == 409
    assert staged.json()["code"] == "revision_not_published"
    latest = _query(client, alpha_headers, unpublished["dataset_id"])
    assert latest.status_code == 409
    assert latest.json()["code"] == "revision_not_published"


def test_limit_cap_and_truncation(client, alpha_headers):
    dataset_id, revision = _publish(client, alpha_headers)
    allowed = _query(
        client, alpha_headers, dataset_id, dimensions=["originating_branch"], limit=500
    )
    assert allowed.status_code == 200
    assert allowed.json()["truncated"] is False

    too_many = _query(client, alpha_headers, dataset_id, limit=501)
    assert too_many.status_code == 422

    truncated = _query(
        client, alpha_headers, dataset_id, dimensions=["originating_branch"], limit=2
    )
    assert truncated.status_code == 200
    body = truncated.json()
    assert body["truncated"] is True
    assert len(body["rows"]) == 2
    assert body["revision"] == revision


def test_tenant_isolation_never_returns_rows_or_artifacts(client, alpha_headers, beta_headers):
    dataset_id, _revision = _publish(client, alpha_headers)
    foreign = _query(client, beta_headers, dataset_id)
    assert foreign.status_code == 404
    assert "rows" not in foreign.json()

    created = client.post(
        "/v1/analytics/analyses",
        json={"name": "Alpha private analysis", "query": _body(dataset_id), "run_now": True},
        headers=alpha_headers,
    )
    assert created.status_code == 201, created.text
    artifact_id = created.json()["id"]

    assert client.get(f"/v1/analytics/analyses/{artifact_id}", headers=beta_headers).status_code == 404
    assert client.delete(f"/v1/analytics/analyses/{artifact_id}", headers=beta_headers).status_code == 404
    listed = client.get("/v1/analytics/analyses", headers=beta_headers).json()
    assert listed == []


def test_artifact_crud_duplicate_name_rerun_and_delete_permissions(
    client, alpha_headers, modeler_headers
):
    dataset_id, _revision = _publish(client, alpha_headers)
    payload = {"name": "Branch volume", "query": _body(dataset_id, dimensions=["originating_branch"]), "run_now": True}
    created = client.post("/v1/analytics/analyses", json=payload, headers=alpha_headers)
    assert created.status_code == 201, created.text
    artifact = created.json()
    artifact_id = artifact["id"]
    assert artifact["row_count"] == 4
    assert artifact["result_digest"]
    assert artifact["last_result"]["evidence_ref"].startswith("ev-")

    duplicate = client.post(
        "/v1/analytics/analyses",
        json={**payload, "run_now": False},
        headers=alpha_headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "duplicate_analysis_name"

    listing = client.get("/v1/analytics/analyses?q=branch", headers=alpha_headers)
    assert listing.status_code == 200
    assert listing.headers["x-total-count"] == "1"
    assert listing.json()[0]["id"] == artifact_id

    reopened = client.get(f"/v1/analytics/analyses/{artifact_id}", headers=alpha_headers)
    assert reopened.status_code == 200
    assert "last_result" not in reopened.json()

    first_run = client.get(f"/v1/analytics/analyses/{artifact_id}?run=true", headers=alpha_headers).json()
    second_run = client.get(f"/v1/analytics/analyses/{artifact_id}?run=true", headers=alpha_headers).json()
    assert first_run["last_result"]["evidence_ref"] != second_run["last_result"]["evidence_ref"]
    assert first_run["result_digest"] == second_run["result_digest"]
    assert second_run["row_count"] == 4

    unrun = client.post(
        "/v1/analytics/analyses",
        json={"name": "Cold analysis", "query": _body(dataset_id), "run_now": False},
        headers=alpha_headers,
    )
    assert unrun.status_code == 201
    cold = unrun.json()
    assert cold["result_digest"] is None
    assert cold["row_count"] == 0
    warmed = client.get(f"/v1/analytics/analyses/{cold['id']}?run=true", headers=alpha_headers).json()
    assert warmed["result_digest"]
    assert warmed["row_count"] == 1

    renamed = client.put(
        f"/v1/analytics/analyses/{artifact_id}",
        json={"name": "Branch volume renamed"},
        headers=alpha_headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Branch volume renamed"
    assert renamed.json()["query"] == artifact["query"]

    forbidden = client.delete(f"/v1/analytics/analyses/{artifact_id}", headers=modeler_headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "forbidden"

    deleted = client.delete(f"/v1/analytics/analyses/{artifact_id}", headers=alpha_headers)
    assert deleted.status_code == 200
    assert client.get(f"/v1/analytics/analyses/{artifact_id}", headers=alpha_headers).status_code == 404
