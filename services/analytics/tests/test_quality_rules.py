from __future__ import annotations

from decisionos_analytics.profiling import create_rule, evaluate_rules, list_rules

CSV = b"""id,amount,label
1,10,AB
2,20,CD
3,,EF
4,20,
5,40,AB
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
    candidates = client.get(f"/v1/datasets/{dataset_id}/grain-candidates", headers=headers).json()
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


def test_each_rule_kind_passes_and_fails_with_exact_counts(client, alpha_headers):
    dataset_id, revision = _publish(client, alpha_headers, CSV, "quality.csv")
    store = client.app.state.store
    tenant = "tenant_alpha"

    rules = {
        "not_null_pass": create_rule(store, tenant, dataset_id, "id", "not_null"),
        "not_null_fail": create_rule(store, tenant, dataset_id, "amount", "not_null"),
        "unique_pass": create_rule(store, tenant, dataset_id, "id", "unique"),
        "unique_fail": create_rule(store, tenant, dataset_id, "amount", "unique"),
        "range_pass": create_rule(store, tenant, dataset_id, "amount", "range", {"min": 0, "max": 100}),
        "range_fail": create_rule(store, tenant, dataset_id, "amount", "range", {"min": 15, "max": 50}),
        "regex_pass": create_rule(store, tenant, dataset_id, "label", "regex", {"pattern": "[A-Z]{2}"}),
        "regex_fail": create_rule(store, tenant, dataset_id, "label", "regex", {"pattern": r"X\d"}),
    }
    assert len(list_rules(store, tenant, dataset_id)) == 8

    results = {result["rule"]["column_name"] + ":" + result["rule"]["kind"] + ":" + result["rule"]["id"]: result
               for result in evaluate_rules(store, dataset_id, tenant_id=tenant, revision=revision)}
    by_id = {result["rule_id"]: result for result in results.values()}

    assert by_id[rules["not_null_pass"]["id"]]["status"] == "pass"
    assert by_id[rules["not_null_pass"]["id"]]["observed"] == {"violations": 0, "checked": 5}
    assert by_id[rules["not_null_fail"]["id"]]["status"] == "fail"
    assert by_id[rules["not_null_fail"]["id"]]["observed"] == {"violations": 1, "checked": 5}

    assert by_id[rules["unique_pass"]["id"]]["status"] == "pass"
    assert by_id[rules["unique_pass"]["id"]]["observed"] == {"violations": 0, "checked": 5}
    assert by_id[rules["unique_fail"]["id"]]["status"] == "fail"
    assert by_id[rules["unique_fail"]["id"]]["observed"] == {"violations": 1, "checked": 4}

    assert by_id[rules["range_pass"]["id"]]["status"] == "pass"
    assert by_id[rules["range_pass"]["id"]]["observed"] == {"violations": 0, "checked": 4}
    assert by_id[rules["range_fail"]["id"]]["status"] == "fail"
    assert by_id[rules["range_fail"]["id"]]["observed"] == {"violations": 1, "checked": 4}

    assert by_id[rules["regex_pass"]["id"]]["status"] == "pass"
    assert by_id[rules["regex_pass"]["id"]]["observed"] == {"violations": 0, "checked": 4}
    assert by_id[rules["regex_fail"]["id"]]["status"] == "fail"
    assert by_id[rules["regex_fail"]["id"]]["observed"] == {"violations": 4, "checked": 4}


def test_quality_api_create_evaluate_and_delete(client, alpha_headers):
    dataset_id, _revision = _publish(client, alpha_headers, CSV, "quality-api.csv")
    created = client.post(
        f"/v1/datasets/{dataset_id}/quality-rules",
        json={"column_name": "amount", "kind": "not_null", "params": {}},
        headers=alpha_headers,
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]
    assert client.get(
        f"/v1/datasets/{dataset_id}/quality-rules", headers=alpha_headers
    ).json()[0]["id"] == rule_id

    store = client.app.state.store
    evaluate_rules(store, dataset_id, tenant_id="tenant_alpha")
    quality = client.get(f"/v1/datasets/{dataset_id}/quality", headers=alpha_headers).json()
    assert quality["rules"][0]["latest_result"]["status"] == "fail"

    deleted = client.delete(
        f"/v1/datasets/{dataset_id}/quality-rules/{rule_id}", headers=alpha_headers
    )
    assert deleted.status_code == 200, deleted.text
    assert client.get(
        f"/v1/datasets/{dataset_id}/quality-rules", headers=alpha_headers
    ).json() == []
