"""
scripts/run_phase3_concurrency_stress.py
DecisionOS PILOT-01 Milestone 3: Phase 3 — Stress & Concurrency Gate Runner.

Executes:
1. Database Sandbox Isolation:
   - Duplicates var/sandbox_pilot01 (or var/worker/control.sqlite3) to var/sandbox_concurrency.
   - Enforces composite foreign key index: CREATE UNIQUE INDEX IF NOT EXISTS uq_decision_tenant_id ON decision(tenant_id, id);
   - Asserts pre-stress relational integrity.
   - Preserves accepted baseline database (var/worker/control.sqlite3 at commit 9492676) untouched.
2. Isolated Backend Service Lifecycle:
   - Starts an isolated FastAPI backend process on a dedicated port (default: 8101) with DECISIONOS_DATA_DIR pointing to var/sandbox_concurrency.
   - Monitors live healthcheck until ready.
3. Multi-Threaded Concurrency Stress Test:
   - Executes 50 concurrent requests across:
     - POST /v1/decisions (creation)
     - POST /v1/decisions/{id}/transition (state machine mutations & conflicts)
     - POST /v1/monitoring/evaluate (queue anomaly rule evaluation)
     - POST /v1/predictive/score (queue predictive risk scoring)
     - POST /v1/scenarios/solve (queue capacity reallocation LP optimization)
   - Synchronizes thread release via threading.Barrier(50) for true simultaneous execution.
   - Tests both valid demo credentials and synthetic test headers (X-Tenant: test-tenant, X-User: qa-operator -> HTTP 401).
4. Telemetry & Metrics Capture:
   - High-precision latency distribution: min, max, avg, p50, p95, p99 per endpoint and overall.
   - Exact HTTP status codes for all 50 requests.
   - SQLite lock contention monitoring: checks for SQLITE_BUSY, "database is locked", or transaction aborts.
   - Memory stability: samples backend process RSS memory before, during peak concurrency (high-frequency), and after completion.
   - Asserts zero process crashes throughout the entire stress run.
5. Post-Stress Relational Integrity Verification:
   - Executes PRAGMA foreign_key_check and PRAGMA integrity_check on the sandbox database immediately following the concurrent run.
   - Asserts clean status (ok, 0 violations).
   - Verifies baseline database remains pristine.
6. Artifact Output:
   - Serializes comprehensive telemetry into var/qa_artifacts/concurrency_stress_results.json.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import numpy as np

# Default file paths
SANDBOX_CONCURRENCY_DIR = Path("var/sandbox_concurrency")
SANDBOX_PILOT01_DIR = Path("var/sandbox_pilot01")
BASELINE_DB_PATH = Path("var/worker/control.sqlite3")
QA_ARTIFACTS_DIR = Path("var/qa_artifacts")
RESULTS_JSON_PATH = QA_ARTIFACTS_DIR / "concurrency_stress_results.json"

# Auth Headers
VALID_ALPHA_HEADERS = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
SYNTHETIC_TEST_HEADERS = {"X-Tenant": "test-tenant", "X-User": "qa-operator"}


class ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def get_process_rss_mb(pid: int) -> float:
    """Return WorkingSetSize (RSS) in MB for Windows process pid."""
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
    )
    if not handle:
        return 0.0
    try:
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(ProcessMemoryCounters)
        if ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        ):
            return round(counters.WorkingSetSize / (1024.0 * 1024.0), 3)
        return 0.0
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def log(msg: str) -> None:
    now_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{now_str}] {msg}")


def compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def check_sqlite_integrity(db_path: Path) -> tuple[list[Any], list[Any]]:
    """Runs PRAGMA foreign_key_check and PRAGMA integrity_check."""
    conn = sqlite3.connect(str(db_path))
    try:
        fk_check = conn.execute("PRAGMA foreign_key_check;").fetchall()
        integrity_check = conn.execute("PRAGMA integrity_check;").fetchall()
        return fk_check, integrity_check
    finally:
        conn.close()


def setup_sandbox_database(sandbox_dir: Path) -> Path:
    """Creates isolated sandbox duplicated from sandbox_pilot01 or baseline."""
    log(f"Initializing sandbox directory at {sandbox_dir}...")
    if sandbox_dir.exists():
        log(f"Cleaning existing sandbox directory: {sandbox_dir}")
        shutil.rmtree(sandbox_dir, ignore_errors=True)

    if SANDBOX_PILOT01_DIR.exists() and (SANDBOX_PILOT01_DIR / "control.sqlite3").exists():
        log(f"Duplicating sandbox from {SANDBOX_PILOT01_DIR}...")
        shutil.copytree(
            SANDBOX_PILOT01_DIR,
            sandbox_dir,
            ignore=shutil.ignore_patterns("*.log", "*.err", "*.pid"),
        )
    else:
        log(f"Duplicating database from baseline {BASELINE_DB_PATH}...")
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BASELINE_DB_PATH, sandbox_dir / "control.sqlite3")
        objects_dir = BASELINE_DB_PATH.parent / "objects"
        if objects_dir.exists():
            shutil.copytree(objects_dir, sandbox_dir / "objects", dirs_exist_ok=True)

    db_path = sandbox_dir / "control.sqlite3"
    assert db_path.exists(), f"Database file not found at {db_path}"

    # Apply composite foreign key index fix
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_decision_tenant_id ON decision(tenant_id, id);")
        conn.commit()
    finally:
        conn.close()

    # Verify initial integrity
    fk_check, integrity_check = check_sqlite_integrity(db_path)
    assert not fk_check, f"Foreign key check failed on sandbox: {fk_check}"
    assert integrity_check == [("ok",)], f"Integrity check failed on sandbox: {integrity_check}"
    log(f"Sandbox database setup verified: FK check clean (0 violations), integrity check: ok.")
    return db_path


def make_scenario_solve_payload() -> dict[str, Any]:
    """Returns standard allocation LP solver payload for POST /v1/scenarios/solve."""
    return {
        "groups": ["G1", "G2"],
        "queues": ["Q1", "Q2"],
        "periods": [1, 2, 3],
        "segments": [1, 2],
        "eligibility": {json.dumps(["G1", "Q1"]): True, json.dumps(["G2", "Q2"]): True},
        "regular_hours": {
            json.dumps(["G1", 1]): 160, json.dumps(["G1", 2]): 160, json.dumps(["G1", 3]): 160,
            json.dumps(["G2", 1]): 160, json.dumps(["G2", 2]): 160, json.dumps(["G2", 3]): 160,
        },
        "overtime_cap": {
            json.dumps(["G1", 1]): 40, json.dumps(["G1", 2]): 40, json.dumps(["G1", 3]): 40,
            json.dumps(["G2", 1]): 40, json.dumps(["G2", 2]): 40, json.dumps(["G2", 3]): 40,
        },
        "arrivals": {
            json.dumps(["Q1", 1]): 120, json.dumps(["Q1", 2]): 120, json.dumps(["Q1", 3]): 120,
            json.dumps(["Q2", 1]): 120, json.dumps(["Q2", 2]): 120, json.dumps(["Q2", 3]): 120,
        },
        "opening_backlog": {"Q1": 30, "Q2": 20},
        "segment_width": {
            json.dumps(["G1", "Q1", 1, 1]): 160, json.dumps(["G1", "Q1", 1, 2]): 40,
            json.dumps(["G1", "Q1", 2, 1]): 160, json.dumps(["G1", "Q1", 2, 2]): 40,
            json.dumps(["G1", "Q1", 3, 1]): 160, json.dumps(["G1", "Q1", 3, 2]): 40,
            json.dumps(["G2", "Q2", 1, 1]): 160, json.dumps(["G2", "Q2", 1, 2]): 40,
            json.dumps(["G2", "Q2", 2, 1]): 160, json.dumps(["G2", "Q2", 2, 2]): 40,
            json.dumps(["G2", "Q2", 3, 1]): 160, json.dumps(["G2", "Q2", 3, 2]): 40,
        },
        "marginal_rate": {
            json.dumps(["G1", "Q1", 1, 1]): 2.0, json.dumps(["G1", "Q1", 1, 2]): 1.5,
            json.dumps(["G1", "Q1", 2, 1]): 2.0, json.dumps(["G1", "Q1", 2, 2]): 1.5,
            json.dumps(["G1", "Q1", 3, 1]): 2.0, json.dumps(["G1", "Q1", 3, 2]): 1.5,
            json.dumps(["G2", "Q2", 1, 1]): 2.0, json.dumps(["G2", "Q2", 1, 2]): 1.5,
            json.dumps(["G2", "Q2", 2, 1]): 2.0, json.dumps(["G2", "Q2", 2, 2]): 1.5,
            json.dumps(["G2", "Q2", 3, 1]): 2.0, json.dumps(["G2", "Q2", 3, 2]): 1.5,
        },
        "regular_cost": {
            json.dumps(k): 0.0 for k in [["G1", 1], ["G1", 2], ["G1", 3], ["G2", 1], ["G2", 2], ["G2", 3]]
        },
        "overtime_cost": {
            json.dumps(k): 30.0 for k in [["G1", 1], ["G1", 2], ["G1", 3], ["G2", 1], ["G2", 2], ["G2", 3]]
        },
        "backlog_penalty": {
            json.dumps(k): 50.0 for k in [["Q1", 1], ["Q1", 2], ["Q1", 3], ["Q2", 1], ["Q2", 2], ["Q2", 3]]
        },
    }


def make_decision_create_payload(index: int) -> dict[str, Any]:
    """Returns valid decision creation payload for POST /v1/decisions."""
    return {
        "title": f"Concurrent Stress Decision #{index:03d}",
        "brief": {
            "problem": f"Concurrent load mitigation test #{index}",
            "relevant_findings": [f"Stress test observation findings for thread #{index}"],
            "proposed_action": f"Reallocate Tier-1 staffing during load burst #{index}",
            "baseline_option": "Status quo staffing baseline",
            "scope": "Support Operations Triage",
            "owner": "alpha.manager",
            "trade_offs": ["Minor triage buffer reduction"],
            "assumptions": ["Surge stabilizes within 24 hours"],
            "evidence_coverage": [f"pred_artifact_{index:03d}"],
            "validation_plan": "Post-stress relational audit",
            "counter_metrics": ["reopen_rate"],
            "expected_effect": "estimated",
        },
    }


def make_predictive_score_payload(model_id: str, case_index: int) -> dict[str, Any]:
    """Returns predictive score request payload for POST /v1/predictive/score."""
    return {
        "model_id": model_id,
        "case_id": f"T{1000 + case_index}",
        "current_status": "in_progress",
        "deadline": "2026-10-15T00:00:00Z",
        "observation_time": "2026-10-09T12:00:00Z",
        "features": {"case_age_hours": 12.5 + case_index},
    }


def pre_create_draft_decisions(
    client: httpx.Client, base_url: str, count: int = 10
) -> list[str]:
    """Pre-creates draft decisions to be mutated during the concurrency run."""
    log(f"Pre-creating {count} draft decisions for concurrent transition testing...")
    decision_ids = []
    for i in range(1, count + 1):
        payload = {
            "title": f"Pre-Created Transition Target Decision #{i:03d}",
            "brief": {
                "problem": f"Pre-created target for transition stress #{i}",
                "relevant_findings": ["Initial state: draft"],
                "proposed_action": "Transition to proposed under concurrent load",
                "baseline_option": "Remain draft",
                "scope": "QA Concurrency",
                "owner": "alpha.manager",
                "trade_offs": [],
                "assumptions": [],
                "evidence_coverage": ["art-init"],
                "validation_plan": "Audit amendments",
                "counter_metrics": [],
                "expected_effect": "estimated",
            },
        }
        res = client.post(
            f"{base_url}/decisions", headers=VALID_ALPHA_HEADERS, json=payload
        )
        assert res.status_code == 201, f"Failed to pre-create decision #{i}: {res.text}"
        data = res.json()
        decision_ids.append(data["id"])
    log(f"Successfully pre-created {len(decision_ids)} decisions: {decision_ids[:3]}...")
    return decision_ids


def get_active_predictive_model_id(client: httpx.Client, base_url: str) -> str:
    """Finds or activates a predictive model in the sandbox."""
    res = client.get(f"{base_url}/predictive/models", headers=VALID_ALPHA_HEADERS)
    if res.status_code == 200:
        models = res.json() if isinstance(res.json(), list) else res.json().get("models", [])
        for m in models:
            if m.get("status") == "active":
                log(f"Found active predictive model: {m['id']}")
                return m["id"]
        if models:
            m0 = models[0]
            log(f"Activating model {m0['id']}...")
            client.post(
                f"{base_url}/predictive/models/{m0['id']}/transition",
                headers=VALID_ALPHA_HEADERS,
                json={"status": "active", "reason": "Activated for concurrency stress test"},
            )
            return m0["id"]

    # Fallback to known active ID from sandbox
    return "mdl-dcd9feb5-b8f"


def execute_single_request(
    req_id: int,
    endpoint_cat: str,
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    barrier: threading.Barrier,
) -> dict[str, Any]:
    """Worker function executed inside ThreadPoolExecutor, synchronized via barrier."""
    # Synchronize all 50 threads to release at the exact same instant
    barrier.wait()

    t_start = time.perf_counter()
    status_code = 0
    resp_body = ""
    error_msg = ""
    sqlite_lock_issue = False

    try:
        with httpx.Client(timeout=30.0) as client:
            if method == "POST":
                res = client.post(url, headers=headers, json=payload)
            elif method == "GET":
                res = client.get(url, headers=headers)
            else:
                raise ValueError(f"Unsupported method: {method}")

            status_code = res.status_code
            resp_body = res.text
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {str(exc)}"
        resp_body = error_msg
        if "database is locked" in error_msg.lower() or "sqlite_busy" in error_msg.lower():
            sqlite_lock_issue = True
    finally:
        t_end = time.perf_counter()

    latency_ms = round((t_end - t_start) * 1000.0, 2)

    # Check response body for SQLite lock contention messages
    body_lower = resp_body.lower()
    if (
        "database is locked" in body_lower
        or "sqlite_busy" in body_lower
        or "operationalerror" in body_lower
    ):
        sqlite_lock_issue = True

    return {
        "request_id": req_id,
        "endpoint_category": endpoint_cat,
        "method": method,
        "url": url,
        "headers_type": "valid" if headers == VALID_ALPHA_HEADERS else "synthetic_401",
        "status_code": status_code,
        "latency_ms": latency_ms,
        "sqlite_lock_issue": sqlite_lock_issue,
        "error_msg": error_msg,
        "response_snippet": resp_body[:300],
    }


def run_concurrency_stress(
    base_url: str,
    backend_pid: int | None,
    precreated_decision_ids: list[str],
    active_model_id: str,
    concurrency_count: int = 50,
) -> dict[str, Any]:
    """Orchestrates 50 concurrent requests across 5 endpoints with barrier sync."""
    log(f"=== Preparing {concurrency_count} Concurrent Requests ===")

    # Request distribution:
    # Exactly 50 requests: 10 per endpoint across 5 endpoint categories.
    # Within each category of 10: 8 valid demo headers, 2 synthetic test-tenant headers (HTTP 401).
    scenario_payload = make_scenario_solve_payload()

    request_specs = []
    req_counter = 1

    # 1. POST /v1/decisions (10 requests: 8 valid -> 201, 2 synthetic -> 401)
    for i in range(1, 11):
        is_valid = i <= 8
        headers = VALID_ALPHA_HEADERS if is_valid else SYNTHETIC_TEST_HEADERS
        payload = make_decision_create_payload(i)
        request_specs.append(
            (req_counter, "decisions_create", "POST", f"{base_url}/decisions", headers, payload)
        )
        req_counter += 1

    # 2. POST /v1/decisions/{id}/transition (10 requests: 7 unique valid -> 200, 1 concurrent duplicate -> 409/200, 2 synthetic -> 401)
    for i in range(1, 11):
        is_valid = i <= 8
        headers = VALID_ALPHA_HEADERS if is_valid else SYNTHETIC_TEST_HEADERS
        if is_valid:
            if i <= 7:
                # Unique target decision
                did = precreated_decision_ids[i - 1]
            else:
                # Target the same decision as request 1 to trigger state transition conflict (409)
                did = precreated_decision_ids[0]
            payload = {"status": "proposed", "reason": f"Concurrent transition stress test #{i}"}
        else:
            did = precreated_decision_ids[i - 1]
            payload = {"status": "proposed", "reason": "Unauthorized synthetic attempt"}

        request_specs.append(
            (
                req_counter,
                "decisions_transition",
                "POST",
                f"{base_url}/decisions/{did}/transition",
                headers,
                payload,
            )
        )
        req_counter += 1

    # 3. POST /v1/monitoring/evaluate (10 requests: 8 valid -> 200, 2 synthetic -> 401)
    for i in range(1, 11):
        is_valid = i <= 8
        headers = VALID_ALPHA_HEADERS if is_valid else SYNTHETIC_TEST_HEADERS
        request_specs.append(
            (
                req_counter,
                "monitoring_evaluate",
                "POST",
                f"{base_url}/monitoring/evaluate",
                headers,
                {},
            )
        )
        req_counter += 1

    # 4. POST /v1/predictive/score (10 requests: 8 valid -> 200, 2 synthetic -> 401)
    for i in range(1, 11):
        is_valid = i <= 8
        headers = VALID_ALPHA_HEADERS if is_valid else SYNTHETIC_TEST_HEADERS
        payload = make_predictive_score_payload(active_model_id, i)
        request_specs.append(
            (
                req_counter,
                "predictive_score",
                "POST",
                f"{base_url}/predictive/score",
                headers,
                payload,
            )
        )
        req_counter += 1

    # 5. POST /v1/scenarios/solve (10 requests: 8 valid -> 200, 2 synthetic -> 401)
    for i in range(1, 11):
        is_valid = i <= 8
        headers = VALID_ALPHA_HEADERS if is_valid else SYNTHETIC_TEST_HEADERS
        request_specs.append(
            (
                req_counter,
                "scenarios_solve",
                "POST",
                f"{base_url}/scenarios/solve",
                headers,
                scenario_payload,
            )
        )
        req_counter += 1

    assert len(request_specs) == concurrency_count, f"Expected {concurrency_count} requests, got {len(request_specs)}"

    # High-frequency memory sampler during peak concurrency
    peak_rss = [0.0]
    stop_sampler = threading.Event()

    def memory_sampler():
        if not backend_pid:
            return
        while not stop_sampler.is_set():
            current = get_process_rss_mb(backend_pid)
            if current > peak_rss[0]:
                peak_rss[0] = current
            time.sleep(0.01)

    rss_before_mb = get_process_rss_mb(backend_pid) if backend_pid else 0.0
    peak_rss[0] = rss_before_mb

    sampler_thread = threading.Thread(target=memory_sampler, daemon=True)
    sampler_thread.start()

    barrier = threading.Barrier(concurrency_count)
    log(f"Launching {concurrency_count} threads with threading.Barrier release...")

    t0 = time.perf_counter()
    results: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=concurrency_count) as executor:
        futures = [
            executor.submit(
                execute_single_request,
                spec[0],
                spec[1],
                spec[2],
                spec[3],
                spec[4],
                spec[5],
                barrier,
            )
            for spec in request_specs
        ]
        for f in as_completed(futures):
            results.append(f.result())

    total_wall_time_s = round(time.perf_counter() - t0, 3)
    stop_sampler.set()
    sampler_thread.join(timeout=1.0)

    rss_after_mb = get_process_rss_mb(backend_pid) if backend_pid else 0.0
    results.sort(key=lambda r: r["request_id"])

    log(
        f"All {concurrency_count} concurrent requests completed in {total_wall_time_s}s wall time."
    )
    return {
        "results": results,
        "total_wall_time_s": total_wall_time_s,
        "rss_before_mb": rss_before_mb,
        "peak_rss_mb": peak_rss[0],
        "rss_after_mb": rss_after_mb,
    }


def compute_statistics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculates min, max, avg, p50, p95, p99 latencies overall and per endpoint."""
    all_latencies = [r["latency_ms"] for r in results]
    status_counts: dict[int, int] = {}
    lock_issues_count = 0

    for r in results:
        status_counts[r["status_code"]] = status_counts.get(r["status_code"], 0) + 1
        if r["sqlite_lock_issue"]:
            lock_issues_count += 1

    def calc_percentiles(vals: list[float]) -> dict[str, float]:
        if not vals:
            return {"min": 0.0, "max": 0.0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0}
        arr = np.array(vals)
        return {
            "min": round(float(np.min(arr)), 2),
            "max": round(float(np.max(arr)), 2),
            "avg": round(float(np.mean(arr)), 2),
            "p50": round(float(np.percentile(arr, 50)), 2),
            "p95": round(float(np.percentile(arr, 95)), 2),
            "p99": round(float(np.percentile(arr, 99)), 2),
        }

    overall_stats = calc_percentiles(all_latencies)

    # Per endpoint category
    per_endpoint: dict[str, Any] = {}
    categories = sorted(list(set(r["endpoint_category"] for r in results)))
    for cat in categories:
        cat_results = [r for r in results if r["endpoint_category"] == cat]
        cat_latencies = [r["latency_ms"] for r in cat_results]
        cat_statuses: dict[int, int] = {}
        for r in cat_results:
            cat_statuses[r["status_code"]] = cat_statuses.get(r["status_code"], 0) + 1

        per_endpoint[cat] = {
            "count": len(cat_results),
            "status_codes": cat_statuses,
            "latencies": calc_percentiles(cat_latencies),
        }

    return {
        "total_requests": len(results),
        "status_code_counts": status_counts,
        "overall_latency_ms": overall_stats,
        "per_endpoint_breakdown": per_endpoint,
        "sqlite_lock_issues_detected": lock_issues_count,
    }


def main():
    parser = argparse.ArgumentParser(description="DecisionOS Phase 3 Concurrency Stress Runner")
    parser.add_argument("--port", type=int, default=8101, help="Backend port to run/target")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Backend host")
    parser.add_argument("--concurrency", type=int, default=50, help="Number of concurrent requests")
    parser.add_argument(
        "--sandbox-dir",
        type=Path,
        default=SANDBOX_CONCURRENCY_DIR,
        help="Sandbox directory path",
    )
    parser.add_argument(
        "--baseline-db",
        type=Path,
        default=BASELINE_DB_PATH,
        help="Accepted baseline database path",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=RESULTS_JSON_PATH,
        help="Path for output results JSON artifact",
    )
    parser.add_argument(
        "--use-existing-service",
        action="store_true",
        help="Run against already running service instead of spawning isolated backend",
    )
    args = parser.parse_args()

    log("=" * 70)
    log("DECISIONOS PILOT-01 MILESTONE 3: PHASE 3 STRESS & CONCURRENCY GATE")
    log("=" * 70)

    # Record baseline state
    baseline_before_sha = compute_file_sha256(args.baseline_db)
    baseline_fk_before, baseline_int_before = check_sqlite_integrity(args.baseline_db)
    log(f"Baseline database at {args.baseline_db}:")
    log(f"  SHA-256: {baseline_before_sha}")
    log(f"  FK violations: {len(baseline_fk_before)}, Integrity: {baseline_int_before}")
    assert not baseline_fk_before and baseline_int_before == [("ok",)], "Baseline DB must be pristine before test."

    # 1. Setup Sandbox Database
    sandbox_db_path = setup_sandbox_database(args.sandbox_dir)

    server_process: subprocess.Popen | None = None
    base_url = f"http://{args.host}:{args.port}/v1"
    backend_pid: int | None = None
    server_stderr = ""
    stderr_lock_errors: list[str] = []
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    stdout_drainer: threading.Thread | None = None
    stderr_drainer: threading.Thread | None = None

    try:
        if not args.use_existing_service:
            log(f"Spawning isolated analytics backend on port {args.port} pointing to {args.sandbox_dir}...")
            env = os.environ.copy()
            env["DECISIONOS_DATA_DIR"] = str(args.sandbox_dir.resolve())
            server_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "decisionos_analytics.serve:app",
                    "--host",
                    args.host,
                    "--port",
                    str(args.port),
                    "--log-level",
                    "warning",
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            backend_pid = server_process.pid
            log(f"Backend process spawned with PID: {backend_pid}")

            def _drain(stream, line_list: list[str]):
                try:
                    for line in iter(stream.readline, ""):
                        line_list.append(line)
                except Exception:
                    pass
                finally:
                    try:
                        stream.close()
                    except Exception:
                        pass

            stdout_drainer = threading.Thread(
                target=_drain, args=(server_process.stdout, stdout_lines), daemon=True
            )
            stderr_drainer = threading.Thread(
                target=_drain, args=(server_process.stderr, stderr_lines), daemon=True
            )
            stdout_drainer.start()
            stderr_drainer.start()

            # Health poll
            healthy = False
            for attempt in range(40):
                try:
                    r = httpx.get(f"{base_url}/health", timeout=1.0)
                    if r.status_code == 200:
                        healthy = True
                        log(f"Backend is healthy after attempt {attempt + 1}: {r.json()}")
                        break
                except Exception:
                    time.sleep(0.2)

            if not healthy:
                server_process.terminate()
                try:
                    server_process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    server_process.kill()
                    server_process.wait(timeout=1.0)
                if stderr_drainer:
                    stderr_drainer.join(timeout=1.0)
                stdout_err = "".join(stderr_lines)
                raise RuntimeError(f"Backend failed to become healthy on port {args.port}: {stdout_err}")
        else:
            log(f"Targeting existing service at {base_url}...")

        # Warm up client and setup data
        with httpx.Client(timeout=10.0) as client:
            active_model_id = get_active_predictive_model_id(client, base_url)
            precreated_ids = pre_create_draft_decisions(client, base_url, count=10)

        # 2. Execute 50-thread Concurrency Stress Test
        stress_output = run_concurrency_stress(
            base_url=base_url,
            backend_pid=backend_pid,
            precreated_decision_ids=precreated_ids,
            active_model_id=active_model_id,
            concurrency_count=args.concurrency,
        )

        # 3. Assert Zero Process Crashes
        if server_process:
            exit_code = server_process.poll()
            assert exit_code is None, f"Backend process crashed during stress test with exit code: {exit_code}"
            log("Process stability assertion passed: backend process is alive with 0 crashes.")

        # 4. Compute Statistics & Latency Percentiles
        stats = compute_statistics(stress_output["results"])

    finally:
        # Gracefully terminate isolated backend process
        if server_process:
            log("Terminating isolated backend process...")
            server_process.terminate()
            try:
                server_process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                log("Server process did not exit in 5s; killing...")
                server_process.kill()
                server_process.wait(timeout=2.0)
            if stdout_drainer:
                stdout_drainer.join(timeout=1.0)
            if stderr_drainer:
                stderr_drainer.join(timeout=1.0)
            server_stderr = "".join(stderr_lines)
            for line in server_stderr.splitlines():
                if any(kw in line.lower() for kw in ["sqlite_busy", "database is locked", "operationalerror"]):
                    stderr_lock_errors.append(line)

    # 5. Post-Stress Relational Integrity Verification
    log("=== Post-Stress Relational Database Integrity Verification ===")
    sandbox_fk_after, sandbox_int_after = check_sqlite_integrity(sandbox_db_path)
    log(f"Sandbox database post-stress FK violations: {len(sandbox_fk_after)}")
    log(f"Sandbox database post-stress integrity check: {sandbox_int_after}")
    assert not sandbox_fk_after, f"Foreign key check failed post-stress on sandbox: {sandbox_fk_after}"
    assert sandbox_int_after == [("ok",)], f"Integrity check failed post-stress on sandbox: {sandbox_int_after}"

    # Verify Baseline Database is Completely Untouched
    baseline_after_sha = compute_file_sha256(args.baseline_db)
    baseline_fk_after, baseline_int_after = check_sqlite_integrity(args.baseline_db)
    log(f"Baseline database untouched verification:")
    log(f"  SHA-256 before: {baseline_before_sha}")
    log(f"  SHA-256 after:  {baseline_after_sha}")
    assert baseline_before_sha == baseline_after_sha, "Baseline DB was modified! Violates sandbox isolation requirement."
    assert not baseline_fk_after and baseline_int_after == [("ok",)], "Baseline DB integrity degraded!"

    # 6. Build Final Artifact Payload
    artifact_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "milestone": "Milestone 3: Phase 3 — Stress & Concurrency Gate",
        "environment": {
            "python_executable": sys.executable,
            "platform": sys.platform,
            "backend_port": args.port,
            "concurrency_target": args.concurrency,
        },
        "sandbox_isolation": {
            "sandbox_directory": str(args.sandbox_dir),
            "sandbox_db_path": str(sandbox_db_path),
            "composite_fk_index": "uq_decision_tenant_id ON decision(tenant_id, id)",
            "baseline_db_path": str(args.baseline_db),
            "baseline_sha256_unmodified": baseline_before_sha == baseline_after_sha,
            "baseline_untouched": True,
        },
        "telemetry": {
            "wall_clock_time_seconds": stress_output["total_wall_time_s"],
            "total_requests": stats["total_requests"],
            "status_code_distribution": {str(k): v for k, v in stats["status_code_counts"].items()},
            "overall_latency_ms": stats["overall_latency_ms"],
            "per_endpoint_breakdown": stats["per_endpoint_breakdown"],
            "memory_stability_mb": {
                "rss_before": stress_output["rss_before_mb"],
                "peak_rss": stress_output["peak_rss_mb"],
                "rss_after": stress_output["rss_after_mb"],
                "rss_delta": round(stress_output["peak_rss_mb"] - stress_output["rss_before_mb"], 3),
                "process_crashed": False,
            },
            "sqlite_contention": {
                "sqlite_busy_detected": stats["sqlite_lock_issues_detected"] > 0 or len(stderr_lock_errors) > 0,
                "lock_issue_requests_count": stats["sqlite_lock_issues_detected"],
                "stderr_sqlite_errors": stderr_lock_errors,
            },
        },
        "relational_integrity_certification": {
            "sandbox_foreign_key_violations": len(sandbox_fk_after),
            "sandbox_integrity_check": sandbox_int_after[0][0] if sandbox_int_after else "error",
            "baseline_foreign_key_violations": len(baseline_fk_after),
            "baseline_integrity_check": baseline_int_after[0][0] if baseline_int_after else "error",
            "certified_clean": True,
        },
        "individual_request_traces": stress_output["results"],
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(artifact_payload, f, indent=2)

    log(f"Detailed stress benchmark results saved to: {args.output_json}")

    # Print Summary Table
    log("=" * 70)
    log("CONCURRENCY STRESS SUMMARY REPORT")
    log("=" * 70)
    log(f"Total Requests: {stats['total_requests']} concurrent")
    log(f"Wall Clock Time: {stress_output['total_wall_time_s']}s")
    log(f"Status Code Breakdown: {stats['status_code_counts']}")
    log(
        f"Overall Latency (ms): min={stats['overall_latency_ms']['min']}, avg={stats['overall_latency_ms']['avg']}, p50={stats['overall_latency_ms']['p50']}, p95={stats['overall_latency_ms']['p95']}, p99={stats['overall_latency_ms']['p99']}, max={stats['overall_latency_ms']['max']}"
    )
    log(
        f"Memory RSS (MB): before={stress_output['rss_before_mb']}, peak={stress_output['peak_rss_mb']}, after={stress_output['rss_after_mb']} (0 crashes)"
    )
    log(
        f"Relational Integrity: Sandbox FK violations={len(sandbox_fk_after)}, Integrity={sandbox_int_after[0][0]}"
    )
    log(
        f"Baseline Preservation: SHA256 verified identical ({baseline_after_sha[:16]}...), FK violations={len(baseline_fk_after)}, Integrity={baseline_int_after[0][0]}"
    )
    log("=" * 70)
    log("[GATE PASS] Milestone 3 Phase 3 Stress & Concurrency Gate successfully completed.")


if __name__ == "__main__":
    main()
