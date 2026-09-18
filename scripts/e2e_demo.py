#!/usr/bin/env python3
"""DecisionOS E2E demo: authorized upload -> safe parse -> confirmed grain -> approved metric.

Runs the full pipeline in-process against the local control plane, validates
results against independently computed golden values, and demonstrates the
safety gates (grain refusal, cross-tenant isolation, uncertified-metric refusal).

Usage: python scripts/e2e_demo.py [--serve]
       --serve additionally starts uvicorn on :8100 for the Nuxt frontend.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "analytics"))

FIXTURES = ROOT / "fixtures" / "support-tickets" / "data"
GOLDEN = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))["tenants"]["tenant_alpha"]

ALPHA = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
MODELER = {"X-Tenant": "tenant_alpha", "X-User": "alpha.modeler"}
BETA = {"X-Tenant": "tenant_beta", "X-User": "beta.manager"}
WINDOW = {"start": "2026-01-01T00:00:00Z", "end": "2026-04-01T00:00:00Z", "timezone": "Asia/Bahrain"}


def step(n: int, msg: str) -> None:
    print(f"\n[{n}] {msg}")


def run_pipeline(client) -> int:
    failures = 0

    def check(label: str, ok: bool) -> None:
        nonlocal failures
        print(f"    {'PASS' if ok else 'FAIL'}  {label}")
        if not ok:
            failures += 1

    step(1, "Authorized upload of tenant_alpha tickets (quarantine -> scan -> bounded parse)")
    r = client.post("/v1/uploads", json={"filename": "tickets_cases.csv", "size_bytes": (FIXTURES / "tenant_alpha/tickets_cases.csv").stat().st_size, "workspace_id": "ws-support-ops"}, headers=ALPHA)
    uid = r.json()["upload_id"]
    data = (FIXTURES / "tenant_alpha" / "tickets_cases.csv").read_bytes()
    client.put(f"/v1/uploads/{uid}/content", content=data, headers=ALPHA)
    fin = client.post(f"/v1/uploads/{uid}/finalize", headers=ALPHA).json()
    dataset_id, revision = fin["dataset_id"], fin["revision"]
    check(f"scan clean, revision {revision} staged & validated", fin["scan"]["verdict"] == "clean" and fin["revision_state"] == "validated")

    prev = client.get(f"/v1/uploads/{uid}/preview", headers=ALPHA).json()
    case_col = next(c for c in prev["columns"] if c["name"] == "case_id")
    check(f"encoding={prev['detected']['encoding']} rows={prev['row_count']} (golden {GOLDEN['rows_total']})", prev["row_count"] == GOLDEN["rows_total"])
    check("leading-zero identifiers preserved as text (QA-001)", case_col["inferred_type"] == "string")

    step(2, "Publishing BEFORE grain confirmation must be refused")
    r = client.post(f"/v1/datasets/{dataset_id}/revisions/{revision}/publish", headers=ALPHA)
    check("422 grain_unconfirmed", r.status_code == 422)

    step(3, "Grain candidates proven over the FULL dataset; owner confirms case_id")
    cands = client.get(f"/v1/uploads/{uid}/grain-candidates", headers=ALPHA).json()
    case_id = next(c for c in cands if c["key_columns"] == ["case_id"])
    check("case_id unique over complete data, zero null components", case_id["unique_over_full_data"] and case_id["null_components"] == 0)
    r = client.post(f"/v1/datasets/{dataset_id}/grain-confirmation", json={"key_columns": ["case_id"]}, headers=ALPHA)
    check("grain confirmed by human actor", r.status_code == 200)

    step(4, "Atomic publication: pointer + outbox event in one transaction")
    r = client.post(f"/v1/datasets/{dataset_id}/revisions/{revision}/publish", headers=ALPHA)
    check("published", r.json().get("status") == "published")
    events = client.get("/v1/jobs/outbox", headers=ALPHA).json()
    check("dataset.revision_published in outbox", any(e["event_type"] == "dataset.revision_published" for e in events))

    step(5, "Uncertified metric query refuses instead of fabricating")
    metric = {
        "metric_id": "metric-first-response-rate", "name": "First response rate", "kind": "ratio",
        "expression": {"kind": "ratio", "numerator_predicates": [{"op": "is_not_null", "field": "first_response_at"}]},
        "eligibility": [{"op": "not_in", "field": "status", "value": ["spam"]}],
        "time_basis": "created_at", "timezone": "Asia/Bahrain", "dataset_id": dataset_id,
    }
    q = {"schema_version": "1.0", "metric_id": metric["metric_id"], "window": WINDOW, "dimensions": ["originating_branch"]}
    r = client.post("/v1/metrics/query", json=q, headers=ALPHA).json()
    check("insufficient_data (not a number)", r["status"] == "insufficient_data" and r["reason_code"] == "metric_not_certified")

    step(6, "Propose (modeler) -> approval by a DIFFERENT actor -> certified query vs golden")
    client.post("/v1/metrics/definitions", json=metric, headers=MODELER)
    v = client.get("/v1/metrics/definitions", headers=MODELER).json()[-1]["version"]
    r = client.post(f"/v1/metrics/definitions/{metric['metric_id']}/approve", json={"version": v, "change_reason": "owner review", "semantic_release_id": "release-1"}, headers=MODELER)
    check("self-approval blocked (403)", r.status_code == 403)
    r = client.post(f"/v1/metrics/definitions/{metric['metric_id']}/approve", json={"version": v, "change_reason": "owner review", "semantic_release_id": "release-1"}, headers=ALPHA)
    check("approved by manager", r.json()["status"] == "approved")
    body = client.post("/v1/metrics/query", json=q, headers=ALPHA).json()
    got = {row["originating_branch"]: row["value"] for row in body["rows"]}
    for branch, g in GOLDEN["per_branch"].items():
        check(f"{branch}: rate={got[branch]:.4f} == golden {g['responded']}/{g['eligible']}={g['responded']/g['eligible']:.4f}", got[branch] == round(g["responded"] / g["eligible"], 6))
    check("ratio computed as ratio of totals (flag)", "ratio_computed_as_ratio_of_totals" in body["quality_flags"])
    check(f"evidence persisted ({body['evidence_ref']})", body["evidence_ref"].startswith("evidence-"))

    step(7, "Median first-response hours matches independently computed golden")
    med = {
        "metric_id": "metric-median-first-response-hours", "name": "Median first response hours", "kind": "duration_percentile",
        "expression": {"kind": "duration_percentile", "start_field": "created_at", "end_field": "first_response_at", "unit": "hours", "quantile": 0.5},
        "eligibility": [{"op": "not_in", "field": "status", "value": ["spam"]}],
        "time_basis": "created_at", "timezone": "Asia/Bahrain", "dataset_id": dataset_id,
    }
    client.post("/v1/metrics/definitions", json=med, headers=MODELER)
    v = client.get("/v1/metrics/definitions", headers=MODELER).json()[-1]["version"]
    client.post(f"/v1/metrics/definitions/{med['metric_id']}/approve", json={"version": v, "change_reason": "reviewed"}, headers=ALPHA)
    rows = client.post("/v1/metrics/query", json={"schema_version": "1.0", "metric_id": med["metric_id"], "window": WINDOW, "dimensions": ["originating_branch"]}, headers=ALPHA).json()["rows"]
    got = {row["originating_branch"]: row["value"] for row in rows}
    for branch, g in GOLDEN["per_branch"].items():
        check(f"{branch}: median={got[branch]:.4f}h golden={g['median_first_response_hours']:.4f}h", abs(got[branch] - g["median_first_response_hours"]) < 0.011)

    step(8, "Adversarial file: duplicate/null key blocks grain confirmation (QA-005)")
    dirty = FIXTURES / "adversarial" / "tickets_cases_dirty.csv"
    r = client.post("/v1/uploads", json={"filename": dirty.name, "size_bytes": dirty.stat().st_size, "workspace_id": "ws-support-ops"}, headers=ALPHA)
    uid2 = r.json()["upload_id"]
    client.put(f"/v1/uploads/{uid2}/content", content=dirty.read_bytes(), headers=ALPHA)
    fin2 = client.post(f"/v1/uploads/{uid2}/finalize", headers=ALPHA).json()
    prev2 = client.get(f"/v1/uploads/{uid2}/preview", headers=ALPHA).json()
    check("malformed row rejected & counted, not silently dropped", len(prev2["rejected_rows"]) == 1)
    check("ambiguous date flagged for explicit parsing rule (QA-002)", any("ambiguous" in i for i in prev2["issues"]))
    r = client.post(f"/v1/datasets/{fin2['dataset_id']}/grain-confirmation", json={"key_columns": ["case_id"]}, headers=ALPHA)
    check("grain_not_proven refusal", r.status_code == 422)

    step(9, "Tenant isolation: tenant_beta cannot see or touch alpha objects (QA-025)")
    for path in (f"/v1/uploads/{uid}/preview", f"/v1/uploads/{uid}/grain-candidates"):
        check(f"404 for {path}", client.get(path, headers=BETA).status_code == 404)
    check("beta sees empty dataset list", client.get("/v1/datasets", headers=BETA).json() == [])

    step(10, "tenant_beta runs its own pipeline independently")
    b = FIXTURES / "tenant_beta" / "tickets_cases.csv"
    r = client.post("/v1/uploads", json={"filename": "tickets_cases.csv", "size_bytes": b.stat().st_size, "workspace_id": "ws-support-ops"}, headers=BETA)
    uid3 = r.json()["upload_id"]
    client.put(f"/v1/uploads/{uid3}/content", content=b.read_bytes(), headers=BETA)
    fin3 = client.post(f"/v1/uploads/{uid3}/finalize", headers=BETA).json()
    check("beta revision validated", fin3["revision_state"] == "validated")

    return failures


def main() -> int:
    import tempfile
    from fastapi.testclient import TestClient
    from decisionos_analytics.api import create_app

    if "--serve" in sys.argv:
        import uvicorn
        data_dir = ROOT / "var" / "e2e"
        print(f"serving demo control plane on http://127.0.0.1:8100 (data: {data_dir})")
        uvicorn.run(create_app(data_dir), host="127.0.0.1", port=8100)
        return 0

    with tempfile.TemporaryDirectory(prefix="dos-e2e-", ignore_cleanup_errors=True) as tmp:
        app = create_app(Path(tmp) / "data")
        with TestClient(app) as client:
            print("=" * 72)
            print("DecisionOS end-to-end demo — synthetic data, golden-checked")
            print("=" * 72)
            failures = run_pipeline(client)
        app.state.store.close()
    print("\n" + ("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED"))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
