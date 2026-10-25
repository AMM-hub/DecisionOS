from __future__ import annotations

from decisionos_analytics.profiling import profile_dataset

CSV = b"""id,amount,label,note
1,10,AB,
2,20,CD,
3,,EF,
4,20,,
5,40,AB,
"""


def _publish(client, headers, data: bytes, filename: str) -> tuple[str, int]:
    response = client.post(
        "/v1/uploads",
        json={"filename": filename, "size_bytes": len(data), "workspace_id": "ws-support-ops"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    upload_id = response.json()["upload_id"]
    assert client.put(f"/v1/uploads/{upload_id}/content", content=data, headers=headers).status_code == 200
    finalized = client.post(f"/v1/uploads/{upload_id}/finalize", headers=headers)
    assert finalized.status_code == 200, finalized.text
    dataset_id = finalized.json()["dataset_id"]
    revision = finalized.json()["revision"]

    candidates = client.get(
        f"/v1/datasets/{dataset_id}/grain-candidates", headers=headers
    ).json()
    unique = next(candidate for candidate in candidates if candidate["unique_over_full_data"])
    assert client.post(
        f"/v1/datasets/{dataset_id}/grain-confirmation",
        json={"key_columns": unique["key_columns"]},
        headers=headers,
    ).status_code == 200
    assert client.post(
        f"/v1/datasets/{dataset_id}/revisions/{revision}/publish", headers=headers
    ).status_code == 200
    return dataset_id, revision


def test_profile_counts_are_exact(client, alpha_headers):
    dataset_id, revision = _publish(client, alpha_headers, CSV, "profile.csv")
    store = client.app.state.store
    profiles = {row["column_name"]: row for row in profile_dataset(store, dataset_id, revision)}

    amount = profiles["amount"]
    assert amount["dtype"] == "integer"
    assert amount["row_count"] == 5
    assert amount["null_count"] == 1
    assert amount["null_rate"] == 0.2
    assert amount["distinct_count"] == 3
    assert amount["min_value"] == 10
    assert amount["max_value"] == 40

    identifier = profiles["id"]
    assert identifier["null_count"] == 0
    assert identifier["null_rate"] == 0.0
    assert identifier["distinct_count"] == 5

    note = profiles["note"]
    assert note["null_count"] == 5
    assert note["null_rate"] == 1.0
    assert note["distinct_count"] == 0
    assert note["min_value"] is None
    assert note["max_value"] is None


def test_profile_route_returns_persisted_rows(client, alpha_headers):
    dataset_id, _revision = _publish(client, alpha_headers, CSV, "profile-route.csv")
    recomputed = client.post(f"/v1/datasets/{dataset_id}/profile", headers=alpha_headers)
    assert recomputed.status_code == 200, recomputed.text
    body = recomputed.json()
    assert body["revision"] == 1
    assert {row["column_name"] for row in body["profile"]} == {"id", "amount", "label", "note"}

    fetched = client.get(f"/v1/datasets/{dataset_id}/quality", headers=alpha_headers)
    assert fetched.status_code == 200, fetched.text
    assert len(fetched.json()["profile"]) == 4
