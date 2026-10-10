"""
scripts/challenge_m3_concurrency.py
Adversarial QA Challenger for Milestone 3: Phase 3 Concurrency & Stress Gate.

Performs empirical verification:
1. Validates all 50 request logs in var/qa_artifacts/concurrency_stress_results.json.
2. Asserts exact HTTP status code distributions:
   - 10 synthetic boundary requests (X-Tenant: test-tenant, X-User: qa-operator) strictly return HTTP 401.
   - 40 valid requests return 200, 201, or 409.
   - Zero HTTP 500 internal server errors.
   - Zero SQLite lock contention / SQLITE_BUSY exceptions.
3. Mathematically recomputes overall and per-endpoint latency percentiles (min, max, avg, p50, p95, p99).
4. Verifies database integrity on both baseline and sandbox SQLite instances.
5. Analyzes concurrency wall-clock duration and thread behavior.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path
import numpy as np

ARTIFACT_PATH = Path("var/qa_artifacts/concurrency_stress_results.json")
BASELINE_DB_PATH = Path("var/worker/control.sqlite3")
SANDBOX_DB_PATH = Path("var/sandbox_concurrency/control.sqlite3")
EXPECTED_BASELINE_SHA256 = "b0aa71c5f6431b8d1ca530eeaf1f9f0b9aeb5b765977be0345ba40f5a985598e"


def calc_percentiles(vals: list[float]) -> dict[str, float]:
    arr = np.array(vals)
    return {
        "min": round(float(np.min(arr)), 2),
        "max": round(float(np.max(arr)), 2),
        "avg": round(float(np.mean(arr)), 2),
        "p50": round(float(np.percentile(arr, 50)), 2),
        "p95": round(float(np.percentile(arr, 95)), 2),
        "p99": round(float(np.percentile(arr, 99)), 2),
    }


def main():
    print("=" * 70)
    print("CHALLENGER M3: EMPIRICAL AUDIT & ADVERSARIAL STRESS CHALLENGE")
    print("=" * 70)

    # 1. Load artifact
    assert ARTIFACT_PATH.exists(), f"Artifact not found at {ARTIFACT_PATH}"
    with open(ARTIFACT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    traces = data.get("individual_request_traces", [])
    telemetry = data.get("telemetry", {})
    certification = data.get("relational_integrity_certification", {})

    print(f"Artifact loaded successfully. Total individual traces: {len(traces)}")
    assert len(traces) == 50, f"Expected exactly 50 individual request traces, found {len(traces)}"

    # 2. Verify all 50 request logs structure & integrity
    expected_categories = {
        "decisions_create": {"method": "POST", "total": 10, "valid": 8, "synthetic": 2},
        "decisions_transition": {"method": "POST", "total": 10, "valid": 8, "synthetic": 2},
        "monitoring_evaluate": {"method": "POST", "total": 10, "valid": 8, "synthetic": 2},
        "predictive_score": {"method": "POST", "total": 10, "valid": 8, "synthetic": 2},
        "scenarios_solve": {"method": "POST", "total": 10, "valid": 8, "synthetic": 2},
    }

    observed_cat_counts = {}
    synthetic_count = 0
    valid_count = 0
    status_counts = {}
    lock_issue_count = 0
    server_error_count = 0

    for idx, trace in enumerate(traces, 1):
        assert trace["request_id"] == idx, f"Trace index mismatch: expected {idx}, got {trace['request_id']}"
        cat = trace["endpoint_category"]
        assert cat in expected_categories, f"Unknown endpoint category: {cat}"
        observed_cat_counts[cat] = observed_cat_counts.get(cat, 0) + 1

        method = trace["method"]
        assert method == expected_categories[cat]["method"], f"Method mismatch in req {idx}: {method}"

        status = trace["status_code"]
        status_counts[status] = status_counts.get(status, 0) + 1

        headers_type = trace["headers_type"]
        if headers_type == "synthetic_401":
            synthetic_count += 1
            assert status == 401, f"Req #{idx} with synthetic headers expected 401, got {status}"
            assert "unauthorized" in trace["response_snippet"].lower() or "detail" in trace["response_snippet"].lower(), (
                f"Req #{idx} response snippet does not indicate auth rejection: {trace['response_snippet']}"
            )
        elif headers_type == "valid":
            valid_count += 1
            assert status in (200, 201, 409), f"Req #{idx} with valid headers returned unexpected status {status}"
        else:
            raise AssertionError(f"Unknown headers_type in trace #{idx}: {headers_type}")

        if status == 500:
            server_error_count += 1

        if trace["sqlite_lock_issue"]:
            lock_issue_count += 1

        # Check for error keywords in snippet
        snippet_lower = trace["response_snippet"].lower()
        if any(term in snippet_lower for term in ["database is locked", "sqlite_busy", "operationalerror"]):
            lock_issue_count += 1

    print(f"Verified 50 traces: {valid_count} valid requests, {synthetic_count} synthetic requests.")
    assert synthetic_count == 10, f"Expected 10 synthetic requests, got {synthetic_count}"
    assert valid_count == 40, f"Expected 40 valid requests, got {valid_count}"
    assert server_error_count == 0, f"Expected 0 HTTP 500 errors, found {server_error_count}"
    assert lock_issue_count == 0, f"Expected 0 lock contention issues, found {lock_issue_count}"

    for cat, exp in expected_categories.items():
        assert observed_cat_counts.get(cat) == exp["total"], f"Category {cat} count mismatch: {observed_cat_counts.get(cat)} != {exp['total']}"

    print(f"Status code breakdown across all 50 requests: {status_counts}")
    assert status_counts.get(401) == 10, f"Expected exactly 10 HTTP 401 responses, got {status_counts.get(401)}"
    assert status_counts.get(201) == 8, f"Expected exactly 8 HTTP 201 responses, got {status_counts.get(201)}"
    assert status_counts.get(200) == 31, f"Expected exactly 31 HTTP 200 responses, got {status_counts.get(200)}"
    assert status_counts.get(409) == 1, f"Expected exactly 1 HTTP 409 response, got {status_counts.get(409)}"

    # 3. Analyze the single 409 conflict request
    conflict_traces = [t for t in traces if t["status_code"] == 409]
    assert len(conflict_traces) == 1, f"Expected exactly 1 conflict trace, found {len(conflict_traces)}"
    conflict_trace = conflict_traces[0]
    print(f"\nConflict Request Analysis:")
    print(f"  Request ID: #{conflict_trace['request_id']}")
    print(f"  Category:   {conflict_trace['endpoint_category']}")
    print(f"  URL:        {conflict_trace['url']}")
    print(f"  Snippet:    {conflict_trace['response_snippet']}")
    assert conflict_trace["endpoint_category"] == "decisions_transition", "409 must occur on decision transition"
    assert "invalid_transition" in conflict_trace["response_snippet"] or "cannot transition" in conflict_trace["response_snippet"].lower() or "409" in conflict_trace["response_snippet"] or "detail" in conflict_trace["response_snippet"].lower(), (
        f"Unexpected snippet for 409: {conflict_trace['response_snippet']}"
    )

    # 4. Latency calculations verification
    all_latencies = [t["latency_ms"] for t in traces]
    synthetic_latencies = [t["latency_ms"] for t in traces if t["headers_type"] == "synthetic_401"]
    valid_latencies = [t["latency_ms"] for t in traces if t["headers_type"] == "valid"]

    print("\n=== Individual Request Trace Table (50 Requests) ===")
    print(f"{'ID':<4} | {'Category':<22} | {'Headers':<14} | {'Status':<6} | {'Latency':<10}")
    print("-" * 65)
    for t in traces:
        print(f"{t['request_id']:02d}   | {t['endpoint_category']:<22} | {t['headers_type']:<14} | {t['status_code']:<6} | {t['latency_ms']:8.2f} ms")

    print(f"\nSynthetic 401 Latencies: min={min(synthetic_latencies):.2f}ms, avg={np.mean(synthetic_latencies):.2f}ms, max={max(synthetic_latencies):.2f}ms")
    print(f"Valid 200/201/409 Latencies: min={min(valid_latencies):.2f}ms, avg={np.mean(valid_latencies):.2f}ms, max={max(valid_latencies):.2f}ms")

    recalculated_overall = calc_percentiles(all_latencies)
    recorded_overall = telemetry.get("overall_latency_ms", {})
    print(f"\nRecorded Overall Latency:     {recorded_overall}")
    print(f"Recalculated Overall Latency: {recalculated_overall}")
    for k in ["min", "max", "avg", "p50", "p95", "p99"]:
        assert recalculated_overall[k] == recorded_overall[k], f"Latency mismatch on {k}: {recalculated_overall[k]} != {recorded_overall[k]}"
    print("Overall latency percentiles mathematically verified.")

    # Per-endpoint category verification
    recorded_endpoints = telemetry.get("per_endpoint_breakdown", {})
    for cat in expected_categories:
        cat_traces = [t for t in traces if t["endpoint_category"] == cat]
        cat_lats = [t["latency_ms"] for t in cat_traces]
        recalc_cat = calc_percentiles(cat_lats)
        rec_cat = recorded_endpoints.get(cat, {}).get("latencies", {})
        print(f"Endpoint {cat:20s} Recalculated: {recalc_cat}")
        print(f"Endpoint {cat:20s} Recorded:     {rec_cat}")
        for k in ["min", "max", "avg", "p50", "p95", "p99"]:
            assert recalc_cat[k] == rec_cat[k], f"Per-endpoint latency mismatch on {cat}.{k}: {recalc_cat[k]} != {rec_cat[k]}"
    print("All per-endpoint latency distributions mathematically verified.")

    # 5. Database Integrity Verification
    print("\n=== Database Relational Integrity Audit ===")
    assert BASELINE_DB_PATH.exists(), f"Baseline DB missing at {BASELINE_DB_PATH}"
    with open(BASELINE_DB_PATH, "rb") as f:
        baseline_sha = hashlib.sha256(f.read()).hexdigest()
    print(f"Baseline SHA-256: {baseline_sha}")
    assert baseline_sha == EXPECTED_BASELINE_SHA256, (
        f"Baseline DB modified! Expected {EXPECTED_BASELINE_SHA256}, got {baseline_sha}"
    )

    conn_base = sqlite3.connect(str(BASELINE_DB_PATH))
    base_fk = conn_base.execute("PRAGMA foreign_key_check;").fetchall()
    base_int = conn_base.execute("PRAGMA integrity_check;").fetchall()
    conn_base.close()
    print(f"Baseline FK violations: {len(base_fk)}, Integrity: {base_int}")
    assert not base_fk, f"Baseline FK violations: {base_fk}"
    assert base_int == [("ok",)], f"Baseline integrity check failed: {base_int}"

    assert SANDBOX_DB_PATH.exists(), f"Sandbox DB missing at {SANDBOX_DB_PATH}"
    conn_sand = sqlite3.connect(str(SANDBOX_DB_PATH))
    sand_fk = conn_sand.execute("PRAGMA foreign_key_check;").fetchall()
    sand_int = conn_sand.execute("PRAGMA integrity_check;").fetchall()
    decision_rows = conn_sand.execute("SELECT count(*) FROM decision;").fetchone()[0]
    indices = [r[1] for r in conn_sand.execute("PRAGMA index_list('decision');").fetchall()]
    conn_sand.close()
    print(f"Sandbox FK violations: {len(sand_fk)}, Integrity: {sand_int}")
    print(f"Sandbox total decisions in DB: {decision_rows}")
    print(f"Sandbox decision indices: {indices}")
    assert not sand_fk, f"Sandbox FK violations: {sand_fk}"
    assert sand_int == [("ok",)], f"Sandbox integrity check failed: {sand_int}"
    assert "uq_decision_tenant_id" in indices, "Composite index uq_decision_tenant_id missing in sandbox"

    # 6. Memory and Telemetry Sanity Checks
    print("\n=== Memory Stability & Concurrency Telemetry ===")
    mem = telemetry.get("memory_stability_mb", {})
    print(f"Memory RSS telemetry: {mem}")
    assert mem.get("process_crashed") is False, "Process crash reported in telemetry!"
    assert mem.get("peak_rss", 0) > 0, "Peak RSS is non-positive"
    assert mem.get("rss_delta") >= 0, "RSS delta is negative"

    sqlite_cont = telemetry.get("sqlite_contention", {})
    print(f"SQLite contention telemetry: {sqlite_cont}")
    assert sqlite_cont.get("sqlite_busy_detected") is False, "sqlite_busy_detected is True"
    assert sqlite_cont.get("lock_issue_requests_count") == 0, "lock_issue_requests_count > 0"
    assert sqlite_cont.get("stderr_sqlite_errors") == [], "stderr_sqlite_errors non-empty"

    wall_time = telemetry.get("wall_clock_time_seconds", 0.0)
    print(f"Wall clock time for 50 requests: {wall_time}s")
    assert 0.5 <= wall_time <= 15.0, f"Wall clock time {wall_time}s out of expected bounds"

    print("\n" + "=" * 70)
    print("ALL 5 EMPIRICAL CHALLENGER ASSERTIONS PASSED WITH ZERO VIOLATIONS.")
    print("=" * 70)


if __name__ == "__main__":
    main()
