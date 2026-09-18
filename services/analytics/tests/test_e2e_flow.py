"""End-to-end: authorized upload -> safe parse -> confirmed grain -> approved metric,
validated against independently computed golden values (spec §29.1)."""

from __future__ import annotations

import json

from conftest import FIXTURES, upload_and_finalize

METRIC_FR = {
    "metric_id": "metric-first-response-rate",
    "name": "First response rate",
    "kind": "ratio",
    "expression": {"kind": "ratio", "numerator_predicates": [{"op": "is_not_null", "field": "first_response_at"}]},
    "eligibility": [{"op": "not_in", "field": "status", "value": ["spam"]}],
    "time_basis": "created_at",
    "timezone": "Asia/Bahrain",
    "dataset_id": None,
}
WINDOW = {"start": "2026-01-01T00:00:00Z", "end": "2026-04-01T00:00:00Z", "timezone": "Asia/Bahrain"}
GOLDEN = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))["tenants"]["tenant_alpha"]


def test_full_flow_upload_to_certified_metric(client, alpha_headers, modeler_headers):
    # 1-2. upload -> quarantine -> scan -> bounded parse
    uid, fin = upload_and_finalize(client, alpha_headers, FIXTURES / "tenant_alpha" / "tickets_cases.csv")
    assert fin["status"] == "scanned"
    dataset_id = fin["dataset_id"]
    assert fin["revision_state"] == "validated"

    # 3. preview reports encoding/dialect/rejections
    prev = client.get(f"/v1/uploads/{uid}/preview", headers=alpha_headers).json()
    assert prev["detected"]["encoding"] in ("utf-8-sig", "utf-8")
    assert prev["row_count"] == GOLDEN["rows_total"]
    assert any(c["name"] == "case_id" and c["inferred_type"] == "string" for c in prev["columns"])

    # publish BEFORE grain confirmation must fail (422)
    r = client.post(f"/v1/datasets/{dataset_id}/revisions/{fin['revision']}/publish", headers=alpha_headers)
    assert r.status_code == 422

    # 4. grain: candidates computed over full data, then human-confirmed
    cands = client.get(f"/v1/uploads/{uid}/grain-candidates", headers=alpha_headers).json()
    case_id = next(c for c in cands if c["key_columns"] == ["case_id"])
    assert case_id["unique_over_full_data"]
    r = client.post(f"/v1/datasets/{dataset_id}/grain-confirmation", json={"key_columns": ["case_id"]}, headers=alpha_headers)
    assert r.status_code == 200

    # 5. atomic publication + outbox event
    r = client.post(f"/v1/datasets/{dataset_id}/revisions/{fin['revision']}/publish", headers=alpha_headers)
    assert r.status_code == 200 and r.json()["status"] == "published"
    events = client.get("/v1/jobs/outbox", headers=alpha_headers).json()
    assert any(e["event_type"] == "dataset.revision_published" and e["tenant_id"] == "tenant_alpha" for e in events)

    # 6. metric not certified yet -> insufficient_data, not a fabricated answer
    r = client.post("/v1/metrics/query", json={"schema_version": "1.0", "metric_id": METRIC_FR["metric_id"], "window": WINDOW, "dimensions": ["originating_branch"]}, headers=alpha_headers)
    assert r.json()["status"] == "insufficient_data"

    # 7. propose (modeler) then approve (manager) — different actors
    r = client.post("/v1/metrics/definitions", json={**METRIC_FR, "dataset_id": dataset_id}, headers=modeler_headers)
    assert r.status_code == 201
    version = r.json()["version"]
    r = client.post(f"/v1/metrics/definitions/{METRIC_FR['metric_id']}/approve", json={"version": version, "change_reason": "owner review"}, headers=modeler_headers)
    assert r.status_code == 403  # self-approval blocked

    r = client.post(f"/v1/metrics/definitions/{METRIC_FR['metric_id']}/approve", json={"version": version, "change_reason": "owner review", "semantic_release_id": "release-1"}, headers=alpha_headers)
    assert r.status_code == 200 and r.json()["status"] == "approved"

    # 8. certified query matches independently computed golden, per branch
    r = client.post("/v1/metrics/query", json={"schema_version": "1.0", "metric_id": METRIC_FR["metric_id"], "window": WINDOW, "dimensions": ["originating_branch"], "limit": 50}, headers=alpha_headers)
    body = r.json()
    assert body["status"] == "answered"
    assert body["semantic_release_id"] == "release-1"
    got = {row["originating_branch"]: row for row in body["rows"]}
    for branch, g in GOLDEN["per_branch"].items():
        expected = g["responded"] / g["eligible"]
        assert got[branch]["value"] == round(expected, 6), (branch, got[branch], expected)
    assert body["evidence_ref"].startswith("evidence-")


def test_median_duration_matches_golden(client, alpha_headers, modeler_headers):
    uid, fin = upload_and_finalize(client, alpha_headers, FIXTURES / "tenant_alpha" / "tickets_cases.csv")
    dataset_id = fin["dataset_id"]
    client.post(f"/v1/datasets/{dataset_id}/grain-confirmation", json={"key_columns": ["case_id"]}, headers=alpha_headers)
    client.post(f"/v1/datasets/{dataset_id}/revisions/{fin['revision']}/publish", headers=alpha_headers)

    med = {
        "metric_id": "metric-median-first-response-hours",
        "name": "Median first response hours",
        "kind": "duration_percentile",
        "expression": {"kind": "duration_percentile", "start_field": "created_at", "end_field": "first_response_at", "unit": "hours", "quantile": 0.5},
        "eligibility": [{"op": "not_in", "field": "status", "value": ["spam"]}],
        "time_basis": "created_at",
        "timezone": "Asia/Bahrain",
        "dataset_id": dataset_id,
    }
    r = client.post("/v1/metrics/definitions", json=med, headers=modeler_headers)
    v = r.json()["version"]
    client.post(f"/v1/metrics/definitions/{med['metric_id']}/approve", json={"version": v, "change_reason": "reviewed"}, headers=alpha_headers)
    rows = client.post("/v1/metrics/query", json={"schema_version": "1.0", "metric_id": med["metric_id"], "window": WINDOW, "dimensions": ["originating_branch"]}, headers=alpha_headers).json()["rows"]
    got = {row["originating_branch"]: row["value"] for row in rows}
    for branch, g in GOLDEN["per_branch"].items():
        assert abs(got[branch] - g["median_first_response_hours"]) < 0.011, (branch, got[branch], g["median_first_response_hours"])


def test_dirty_file_blocks_grain_confirmation(client, alpha_headers):
    uid, fin = upload_and_finalize(client, alpha_headers, FIXTURES / "adversarial" / "tickets_cases_dirty.csv")
    prev = client.get(f"/v1/uploads/{uid}/preview", headers=alpha_headers).json()
    assert len(prev["rejected_rows"]) == 1
    cands = client.get(f"/v1/uploads/{uid}/grain-candidates", headers=alpha_headers).json()
    case_id = next(c for c in cands if c["key_columns"] == ["case_id"])
    assert case_id["unique_over_full_data"] is False  # QA-005: fails with evidence, no silent pass
    assert case_id["duplicate_examples"]
    r = client.post(f"/v1/datasets/{fin['dataset_id']}/grain-confirmation", json={"key_columns": ["case_id"]}, headers=alpha_headers)
    assert r.status_code == 422
    # and therefore publishing is blocked until a genuinely unique grain is confirmed
    r = client.post(f"/v1/datasets/{fin['dataset_id']}/revisions/{fin['revision']}/publish", headers=alpha_headers)
    assert r.status_code == 422


def test_cross_tenant_isolation_denies_without_disclosure(client, alpha_headers, beta_headers):
    uid, _ = upload_and_finalize(client, alpha_headers, FIXTURES / "tenant_alpha" / "tickets_cases.csv")
    for path in (f"/v1/uploads/{uid}/preview", f"/v1/uploads/{uid}/grain-candidates"):
        assert client.get(path, headers=beta_headers).status_code == 404  # QA-025: no existence disclosure
    assert client.post(f"/v1/uploads/{uid}/finalize", headers=beta_headers).status_code == 404
    assert client.get(f"/v1/datasets", headers=beta_headers).json() == []


def test_unknown_tenant_or_user_unauthenticated(client):
    assert client.get("/v1/datasets", headers={"X-Tenant": "tenant_ghost", "X-User": "alpha.manager"}).status_code == 401
    assert client.get("/v1/datasets", headers={"X-Tenant": "tenant_alpha", "X-User": "beta.manager"}).status_code == 404
