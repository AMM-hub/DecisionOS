"""
scripts/adversarial_challenger_concurrency_audit.py
Adversarial QA Challenger Empirical Audit & Stress Test Suite for Milestone 3.

Empirically verifies:
1. Baseline DB preservation (var/worker/control.sqlite3 SHA-256, 0 FK violations, integrity ok).
2. Existing sandbox DB integrity (var/sandbox_concurrency/control.sqlite3, 0 FK violations, integrity ok).
3. QA Artifact verification (var/qa_artifacts/concurrency_stress_results.json invariants, distributions, latencies).
4. Barrier synchronization release jitter across 50 threads.
5. Adversarial 50-thread pure-write stress test on an isolated temporary sandbox to verify SQLite concurrency resilience.
6. Final re-assertion of baseline preservation.
"""

from __future__ import annotations

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
from pathlib import Path
import httpx
import numpy as np

BASELINE_DB_PATH = Path("var/worker/control.sqlite3")
SANDBOX_CONCURRENCY_DB_PATH = Path("var/sandbox_concurrency/control.sqlite3")
QA_RESULTS_PATH = Path("var/qa_artifacts/concurrency_stress_results.json")
EXPECTED_BASELINE_SHA = "b0aa71c5f6431b8d1ca530eeaf1f9f0b9aeb5b765977be0345ba40f5a985598e"
TEMP_SANDBOX_DIR = Path("var/sandbox_challenger_temp")
PORT = 8109


def log(msg: str) -> None:
    now_str = time.strftime("%H:%M:%S")
    print(f"[{now_str}] {msg}")


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def check_sqlite(db_path: Path) -> tuple[list, list]:
    conn = sqlite3.connect(str(db_path))
    try:
        fk = conn.execute("PRAGMA foreign_key_check;").fetchall()
        ic = conn.execute("PRAGMA integrity_check;").fetchall()
        return fk, ic
    finally:
        conn.close()


def test_1_baseline_preservation():
    log("=== Test 1: Baseline Preservation Audit ===")
    assert BASELINE_DB_PATH.exists(), f"Baseline DB missing: {BASELINE_DB_PATH}"
    sha = compute_sha256(BASELINE_DB_PATH)
    log(f"Baseline DB SHA-256: {sha}")
    assert sha == EXPECTED_BASELINE_SHA, f"Baseline DB hash mismatch: {sha} != {EXPECTED_BASELINE_SHA}"

    fk, ic = check_sqlite(BASELINE_DB_PATH)
    log(f"Baseline FK violations: {len(fk)}, Integrity: {ic}")
    assert not fk, f"Baseline FK violations found: {fk}"
    assert ic == [("ok",)], f"Baseline integrity check failed: {ic}"
    log("Test 1 PASS: Baseline database is pristine and untouched.")


def test_2_sandbox_concurrency_integrity():
    log("=== Test 2: Sandbox Concurrency Integrity Audit ===")
    assert SANDBOX_CONCURRENCY_DB_PATH.exists(), f"Sandbox DB missing: {SANDBOX_CONCURRENCY_DB_PATH}"
    fk, ic = check_sqlite(SANDBOX_CONCURRENCY_DB_PATH)
    log(f"Sandbox FK violations: {len(fk)}, Integrity: {ic}")
    assert not fk, f"Sandbox FK violations found: {fk}"
    assert ic == [("ok",)], f"Sandbox integrity check failed: {ic}"

    conn = sqlite3.connect(str(SANDBOX_CONCURRENCY_DB_PATH))
    try:
        count = conn.execute("SELECT count(*) FROM decision").fetchone()[0]
        log(f"Total decisions recorded in sandbox: {count}")
        assert count > 0, "No decisions found in sandbox DB"
    finally:
        conn.close()
    log("Test 2 PASS: Sandbox database relational integrity is 100% clean.")


def test_3_qa_results_artifact():
    log("=== Test 3: QA Results Artifact Validation ===")
    assert QA_RESULTS_PATH.exists(), f"Results artifact missing: {QA_RESULTS_PATH}"
    with open(QA_RESULTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    telemetry = data["telemetry"]
    certification = data["relational_integrity_certification"]
    traces = data["individual_request_traces"]

    assert telemetry["total_requests"] == 50, f"Expected 50 requests, got {telemetry['total_requests']}"
    assert len(traces) == 50, f"Expected 50 traces, got {len(traces)}"

    status_dist = telemetry["status_code_distribution"]
    log(f"Status distribution in artifact: {status_dist}")
    assert status_dist.get("201") == 8, f"Expected 8 201s, got {status_dist.get('201')}"
    assert status_dist.get("401") == 10, f"Expected 10 401s, got {status_dist.get('401')}"
    assert status_dist.get("409") == 1, f"Expected 1 409, got {status_dist.get('409')}"
    assert status_dist.get("200") == 31, f"Expected 31 200s, got {status_dist.get('200')}"
    assert "500" not in status_dist, "Found HTTP 500 in status distribution!"

    # Contention check
    contention = telemetry["sqlite_contention"]
    assert contention["sqlite_busy_detected"] is False, "sqlite_busy_detected is True"
    assert contention["lock_issue_requests_count"] == 0, "lock issues > 0"

    # Certification check
    assert certification["sandbox_foreign_key_violations"] == 0
    assert certification["sandbox_integrity_check"] == "ok"
    assert certification["baseline_foreign_key_violations"] == 0
    assert certification["baseline_integrity_check"] == "ok"
    assert data["sandbox_isolation"]["baseline_sha256_unmodified"] is True
    assert certification["certified_clean"] is True

    # Mathematical percentile check
    latencies = [t["latency_ms"] for t in traces]
    arr = np.array(latencies)
    assert round(float(np.min(arr)), 2) == telemetry["overall_latency_ms"]["min"]
    assert round(float(np.max(arr)), 2) == telemetry["overall_latency_ms"]["max"]
    assert round(float(np.percentile(arr, 50)), 2) == telemetry["overall_latency_ms"]["p50"]
    assert round(float(np.percentile(arr, 95)), 2) == telemetry["overall_latency_ms"]["p95"]
    assert round(float(np.percentile(arr, 99)), 2) == telemetry["overall_latency_ms"]["p99"]

    log("Test 3 PASS: QA Results JSON artifact passed all schema and mathematical checks.")


def test_4_barrier_synchronization_jitter():
    log("=== Test 4: Barrier Synchronization Jitter Analysis ===")
    barrier = threading.Barrier(50)
    release_times_ns = [0] * 50

    def worker(idx):
        barrier.wait()
        release_times_ns[idx] = time.perf_counter_ns()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    delta_ms = (max(release_times_ns) - min(release_times_ns)) / 1e6
    log(f"Barrier 50-thread release delta: {delta_ms:.3f} ms")
    assert delta_ms < 15.0, f"Thread release spread is too wide: {delta_ms} ms"
    log("Test 4 PASS: Barrier synchronization verified to release all 50 threads within sub-millisecond to low millisecond precision.")


def test_5_adversarial_pure_write_stress():
    log("=== Test 5: Adversarial 50-Thread Pure-Write Concurrency Stress ===")
    if TEMP_SANDBOX_DIR.exists():
        shutil.rmtree(TEMP_SANDBOX_DIR, ignore_errors=True)
    TEMP_SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BASELINE_DB_PATH, TEMP_SANDBOX_DIR / "control.sqlite3")
    objects_src = BASELINE_DB_PATH.parent / "objects"
    if objects_src.exists():
        shutil.copytree(objects_src, TEMP_SANDBOX_DIR / "objects", dirs_exist_ok=True)

    # Composite index
    conn = sqlite3.connect(str(TEMP_SANDBOX_DIR / "control.sqlite3"))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_decision_tenant_id ON decision(tenant_id, id);")
    conn.commit()
    conn.close()

    env = os.environ.copy()
    env["DECISIONOS_DATA_DIR"] = str(TEMP_SANDBOX_DIR.resolve())
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "decisionos_analytics.serve:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--log-level",
            "warning",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    base_url = f"http://127.0.0.1:{PORT}/v1"
    healthy = False
    for _ in range(30):
        try:
            r = httpx.get(f"{base_url}/health", timeout=1.0)
            if r.status_code == 200:
                healthy = True
                break
        except Exception:
            time.sleep(0.2)

    assert healthy, "Temporary backend failed to boot"
    log("Temporary test backend healthy on port 8109.")

    try:
        barrier = threading.Barrier(50)
        results = []

        def write_worker(idx: int):
            headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
            payload = {
                "title": f"Adversarial Stress Decision #{idx:03d}",
                "brief": {
                    "problem": f"Pure write stress test #{idx}",
                    "relevant_findings": ["Adversarial check"],
                    "proposed_action": "Heavy concurrent write",
                    "baseline_option": "Status quo",
                    "scope": "QA Audit",
                    "owner": "alpha.manager",
                    "trade_offs": [],
                    "assumptions": [],
                    "evidence_coverage": [],
                    "validation_plan": "Audit",
                    "counter_metrics": [],
                    "expected_effect": "estimated",
                },
            }
            barrier.wait()
            t0 = time.perf_counter()
            with httpx.Client(timeout=30.0) as client:
                res = client.post(f"{base_url}/decisions", headers=headers, json=payload)
                t1 = time.perf_counter()
                return {"id": idx, "status": res.status_code, "latency_ms": (t1 - t0) * 1000, "text": res.text}

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(write_worker, i) for i in range(1, 51)]
            for f in as_completed(futures):
                results.append(f.result())

        status_counts = {}
        for r in results:
            status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

        log(f"Adversarial 50 pure write status counts: {status_counts}")
        assert status_counts.get(201) == 50, f"Expected all 50 pure writes to return 201, got {status_counts}"
        assert proc.poll() is None, "Backend crashed under pure write stress!"

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2.0)

    # Post stress integrity check on temp sandbox
    temp_fk, temp_ic = check_sqlite(TEMP_SANDBOX_DIR / "control.sqlite3")
    log(f"Temp sandbox FK violations: {len(temp_fk)}, Integrity: {temp_ic}")
    assert not temp_fk, f"FK violations on temp sandbox: {temp_fk}"
    assert temp_ic == [("ok",)], f"Integrity check failed: {temp_ic}"

    # Clean up temp sandbox
    shutil.rmtree(TEMP_SANDBOX_DIR, ignore_errors=True)
    log("Test 5 PASS: Pure-write concurrency stress executed with 100% HTTP 201, 0 crashes, clean integrity.")


def test_6_final_baseline_recheck():
    log("=== Test 6: Final Baseline Preservation Re-Check ===")
    sha = compute_sha256(BASELINE_DB_PATH)
    log(f"Final Baseline DB SHA-256: {sha}")
    assert sha == EXPECTED_BASELINE_SHA, f"Baseline DB hash changed! {sha} != {EXPECTED_BASELINE_SHA}"
    fk, ic = check_sqlite(BASELINE_DB_PATH)
    assert not fk and ic == [("ok",)], "Baseline DB corrupted!"
    log("Test 6 PASS: Baseline database remains 100% pristine and untouched.")


def main():
    log("======================================================================")
    log("STARTING CHALLENGER M3 EMPIRICAL AUDIT SUITE")
    log("======================================================================")
    test_1_baseline_preservation()
    test_2_sandbox_concurrency_integrity()
    test_3_qa_results_artifact()
    test_4_barrier_synchronization_jitter()
    test_5_adversarial_pure_write_stress()
    test_6_final_baseline_recheck()
    log("======================================================================")
    log("CHALLENGER AUDIT COMPLETE: ALL 6 EMPIRICAL TESTS PASSED.")
    log("VERDICT: APPROVE.")
    log("======================================================================")


if __name__ == "__main__":
    main()
