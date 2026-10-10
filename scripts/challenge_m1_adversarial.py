"""
scripts/adversarial_challenge_m1.py
Empirical Adversarial Challenge Suite for Milestone 1:
1. Dataset Quality Validation Gate Stress Testing (POST /v1/pilots/{id}/validate-data)
   - Inverted timestamps
   - Missing grain columns (case ID, timestamp, status)
   - Completion before creation
   - Empty CSV / 0-row payload
   - Unparseable / corrupted timestamps
   - Null case ID and timestamp values
   - Non-existent dataset revision
2. Synthetic 50-Ticket Dataset Deep Forensic Audit (var/qa_artifacts/synthetic_50_tickets.csv)
   - Ticket ID uniqueness
   - Strict chronological ordering per case
   - Date format validity, time ranges, and leak detection (no epoch, no invalid bounds)
   - Lifecycle state transition validity
3. SQLite Relational Integrity and Edge Cases (var/sandbox_pilot01/control.sqlite3)
   - Orphaned foreign key insertion rejection under PRAGMA foreign_keys = ON
   - Conflicting / duplicate primary key and unique constraint enforcement
   - Detection of orphans via PRAGMA foreign_key_check when forced
   - Post-challenge PRAGMA integrity_check and PRAGMA foreign_key_check certification
"""

import io
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import polars as pl

API_BASE_URL = "http://localhost:8100/v1"
SANDBOX_DB_PATH = Path("var/sandbox_pilot01/control.sqlite3")
CSV_ARTIFACT_PATH = Path("var/qa_artifacts/synthetic_50_tickets.csv")

AUTH_HEADERS = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}

results = {
    "validation_gate_stress_tests": [],
    "synthetic_dataset_audit": {},
    "sqlite_relational_integrity": [],
    "overall_verdict": "PENDING",
}


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ============================================================================
# Section 1: Synthetic 50-Ticket Dataset Deep Forensic Audit
# ============================================================================
def audit_synthetic_dataset() -> dict:
    log("=== Section 1: Deep Forensic Audit of Synthetic 50-Ticket Dataset ===")
    assert CSV_ARTIFACT_PATH.exists(), f"Artifact not found: {CSV_ARTIFACT_PATH}"

    df = pl.read_csv(CSV_ARTIFACT_PATH)
    total_rows = df.height
    expected_cols = [
        "ticket_id", "created_at", "timestamp", "status", "queue", "team",
        "owner", "priority", "category", "sla_deadline", "reopen", "transfer"
    ]
    actual_cols = df.columns
    cols_match = actual_cols == expected_cols
    assert cols_match, f"Columns do not match expected schema: {actual_cols}"

    unique_tickets = df["ticket_id"].unique().to_list()
    total_unique_tickets = len(unique_tickets)
    assert total_unique_tickets == 50, f"Expected 50 unique tickets, got {total_unique_tickets}"

    # Check nulls across all columns
    null_counts = {col: int(df[col].is_null().sum()) for col in df.columns}
    total_nulls = sum(null_counts.values())
    assert total_nulls == 0, f"Found nulls in dataset: {null_counts}"

    # Chronological checks
    chronological_inversions = 0
    inconsistent_created_at = 0
    ts_before_created_at = 0
    sla_before_created_at = 0
    completed_before_created = 0
    invalid_date_formats = 0
    suspicious_epoch_leaks = 0

    now_year = 2026
    min_ts = None
    max_ts = None

    for tid in unique_tickets:
        sub = df.filter(pl.col("ticket_id") == tid)
        sub_rows = sub.to_dicts()
        first_created_dt = None
        last_dt = None
        statuses = []

        for r in sub_rows:
            try:
                dt_ts = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
                dt_created = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
                dt_sla = datetime.fromisoformat(r["sla_deadline"].replace("Z", "+00:00"))
            except Exception:
                invalid_date_formats += 1
                continue

            # Update global bounds
            if min_ts is None or dt_ts < min_ts:
                min_ts = dt_ts
            if max_ts is None or dt_ts > max_ts:
                max_ts = dt_ts

            # Leak detection (e.g. 1970 Unix epoch or distant years)
            if dt_ts.year < 2020 or dt_ts.year > now_year + 1:
                suspicious_epoch_leaks += 1

            if first_created_dt is None:
                first_created_dt = dt_created
            elif dt_created != first_created_dt:
                inconsistent_created_at += 1

            if dt_ts < dt_created:
                ts_before_created_at += 1

            if dt_sla <= dt_created:
                sla_before_created_at += 1

            if last_dt is not None and dt_ts < last_dt:
                chronological_inversions += 1
            last_dt = dt_ts

            statuses.append(r["status"])

        if "created" in statuses and "completed" in statuses:
            if statuses.index("completed") < statuses.index("created"):
                completed_before_created += 1

    status_counts = {r["status"]: int(r["count"]) for r in df["status"].value_counts().to_dicts()}
    audit_results = {
        "total_rows": total_rows,
        "total_unique_tickets": total_unique_tickets,
        "schema_columns_verified": cols_match,
        "total_nulls": total_nulls,
        "chronological_inversions": chronological_inversions,
        "inconsistent_created_at": inconsistent_created_at,
        "ts_before_created_at": ts_before_created_at,
        "sla_before_created_at": sla_before_created_at,
        "completed_before_created": completed_before_created,
        "invalid_date_formats": invalid_date_formats,
        "suspicious_epoch_leaks": suspicious_epoch_leaks,
        "min_timestamp": min_ts.isoformat() if min_ts else None,
        "max_timestamp": max_ts.isoformat() if max_ts else None,
        "status_distribution": status_counts,
        "verdict": "PASS" if (
            total_unique_tickets == 50
            and total_rows == 138
            and chronological_inversions == 0
            and inconsistent_created_at == 0
            and ts_before_created_at == 0
            and completed_before_created == 0
            and invalid_date_formats == 0
            and suspicious_epoch_leaks == 0
        ) else "FAIL",
    }

    log(f"Dataset Audit Result: {audit_results['verdict']}")
    log(f"  Rows: {total_rows}, Unique Tickets: {total_unique_tickets}")
    log(f"  Chronological Inversions: {chronological_inversions}")
    log(f"  Completed before Created: {completed_before_created}")
    log(f"  Null Values: {total_nulls}")
    log(f"  Min TS: {audit_results['min_timestamp']} | Max TS: {audit_results['max_timestamp']}")
    results["synthetic_dataset_audit"] = audit_results
    return audit_results


# ============================================================================
# Section 2: Validation Gate Stress Testing (POST /v1/pilots/{id}/validate-data)
# ============================================================================
def stress_test_validation_gate(client: httpx.Client) -> list[dict]:
    log("=== Section 2: Stress-Testing Dataset Quality Validation Gate ===")
    tests = []

    # Bootstrap an adversarial testing pilot contract so we have an isolated pilot
    adv_dataset_id = f"ds-adv-{int(time.time())}"
    
    # Register dataset in SQLite
    con = sqlite3.connect(str(SANDBOX_DB_PATH), timeout=15.0)
    cur = con.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO dataset (tenant_id, id, workspace_id, name, published_revision, created_at)
        VALUES ('tenant_alpha', ?, 'ws-support-ops', ?, 1, '2026-10-09T00:00:00Z')
        """,
        (adv_dataset_id, f"Adversarial Stress Test Dataset {adv_dataset_id}"),
    )
    con.commit()
    con.close()

    boot_res = client.post(
        f"{API_BASE_URL}/pilots/bootstrap",
        headers=AUTH_HEADERS,
        json={
            "name": "Adversarial Stress Pilot",
            "domain": "support_ticket_operations",
            "owner": "alpha.manager",
            "dataset_id": adv_dataset_id,
            "dataset_revision": 1,
        },
    )
    assert boot_res.status_code == 201, f"Failed to bootstrap adversarial pilot: {boot_res.text}"
    adv_pilot_id = boot_res.json()["pilot"]["id"]
    log(f"Bootstrapped isolated adversarial test pilot: {adv_pilot_id}")

    # Helper function to refresh dataset with given CSV
    def refresh_csv(csv_content: str):
        return client.post(
            f"{API_BASE_URL}/pilots/{adv_pilot_id}/refresh",
            headers=AUTH_HEADERS,
            json={"dataset_id": adv_dataset_id, "csv_content": csv_content},
        )

    # Helper function to validate pilot dataset
    def validate_pilot(revision: int = None, **extra_body):
        payload = {"dataset_id": adv_dataset_id}
        if revision is not None:
            payload["dataset_revision"] = revision
        payload.update(extra_body)
        return client.post(
            f"{API_BASE_URL}/pilots/{adv_pilot_id}/validate-data",
            headers=AUTH_HEADERS,
            json=payload,
        )

    # ------------------------------------------------------------------------
    # Test 2.1: Empty CSV payload (0 rows) via POST /refresh
    # ------------------------------------------------------------------------
    log("--- Test 2.1: Empty CSV Payload (0 rows) ---")
    r_empty = refresh_csv("")
    test_2_1 = {
        "name": "Empty CSV payload via refresh endpoint",
        "description": "Sending an empty CSV string should be rejected with 422 refresh_failed",
        "http_status": r_empty.status_code,
        "passed": r_empty.status_code == 422 and "empty" in r_empty.text.lower(),
        "response": r_empty.json() if r_empty.status_code == 422 else r_empty.text,
    }
    tests.append(test_2_1)
    log(f"Test 2.1 Result: {'PASS' if test_2_1['passed'] else 'FAIL'} (HTTP {r_empty.status_code})")

    # ------------------------------------------------------------------------
    # Test 2.2: Inverted Timestamps (Chronological regression within a ticket)
    # ------------------------------------------------------------------------
    log("--- Test 2.2: Inverted Timestamps Payload ---")
    inverted_csv = """ticket_id,created_at,timestamp,status,queue,team,owner,priority,category,sla_deadline,reopen,transfer
T9001,2026-10-09T10:00:00Z,2026-10-09T10:00:00Z,created,Tier1,AlphaTeam,alice,medium,billing,2026-10-10T10:00:00Z,0,0
T9001,2026-10-09T10:00:00Z,2026-10-09T09:30:00Z,in_progress,Tier1,AlphaTeam,alice,medium,billing,2026-10-10T10:00:00Z,0,0
T9001,2026-10-09T10:00:00Z,2026-10-09T11:00:00Z,completed,Tier1,AlphaTeam,alice,medium,billing,2026-10-10T10:00:00Z,0,0
"""
    r_ref = refresh_csv(inverted_csv)
    assert r_ref.status_code == 200, f"Refresh failed: {r_ref.text}"
    rev_inverted = r_ref.json()["dataset_revision"]

    r_val = validate_pilot(revision=rev_inverted)
    assert r_val.status_code == 200
    val_data = r_val.json()
    passed = (
        val_data.get("status") == "BLOCKED"
        and any("ordering" in r.lower() for r in val_data.get("reasons", []))
        and val_data.get("metrics", {}).get("out_of_order_cases", 0) > 0
    )
    test_2_2 = {
        "name": "Inverted Timestamps Payload",
        "description": "Event 2 timestamp earlier than Event 1 must trigger BLOCKED gate with out-of-order metric",
        "status": val_data.get("status"),
        "reasons": val_data.get("reasons"),
        "metrics": val_data.get("metrics"),
        "passed": passed,
    }
    tests.append(test_2_2)
    log(f"Test 2.2 Result: {'PASS' if passed else 'FAIL'} (status: {val_data.get('status')}, reasons: {val_data.get('reasons')})")

    # ------------------------------------------------------------------------
    # Test 2.3: Completion Before Creation
    # ------------------------------------------------------------------------
    log("--- Test 2.3: Completion Before Creation Payload ---")
    comp_before_creat_csv = """ticket_id,created_at,timestamp,status,queue,team,owner,priority,category,sla_deadline,reopen,transfer
T9002,2026-10-09T12:00:00Z,2026-10-09T09:00:00Z,completed,Tier1,AlphaTeam,alice,high,technical,2026-10-10T12:00:00Z,0,0
T9002,2026-10-09T12:00:00Z,2026-10-09T12:00:00Z,created,Tier1,AlphaTeam,alice,high,technical,2026-10-10T12:00:00Z,0,0
"""
    r_ref = refresh_csv(comp_before_creat_csv)
    assert r_ref.status_code == 200
    rev_comp = r_ref.json()["dataset_revision"]

    r_val = validate_pilot(revision=rev_comp)
    assert r_val.status_code == 200
    val_data = r_val.json()
    passed = (
        val_data.get("status") == "BLOCKED"
        and any("completion before creation" in r.lower() for r in val_data.get("reasons", []))
        and val_data.get("metrics", {}).get("completion_before_creation_cases", 0) > 0
    )
    test_2_3 = {
        "name": "Completion Before Creation Payload",
        "description": "Completed event timestamp earlier than created timestamp must trigger BLOCKED",
        "status": val_data.get("status"),
        "reasons": val_data.get("reasons"),
        "metrics": val_data.get("metrics"),
        "passed": passed,
    }
    tests.append(test_2_3)
    log(f"Test 2.3 Result: {'PASS' if passed else 'FAIL'} (status: {val_data.get('status')}, reasons: {val_data.get('reasons')})")

    # ------------------------------------------------------------------------
    # Test 2.4: Missing Grain Column (Missing Ticket ID Column)
    # ------------------------------------------------------------------------
    log("--- Test 2.4: Missing Grain Column (No ticket_id/case_id) ---")
    missing_case_csv = """timestamp,status,queue,team,owner,priority,category,sla_deadline,reopen,transfer
2026-10-09T10:00:00Z,created,Tier1,AlphaTeam,alice,medium,billing,2026-10-10T10:00:00Z,0,0
2026-10-09T11:00:00Z,completed,Tier1,AlphaTeam,alice,medium,billing,2026-10-10T10:00:00Z,0,0
"""
    r_ref = refresh_csv(missing_case_csv)
    assert r_ref.status_code == 200
    rev_no_case = r_ref.json()["dataset_revision"]

    r_val = validate_pilot(revision=rev_no_case)
    assert r_val.status_code == 200
    val_data = r_val.json()
    passed = (
        val_data.get("status") == "BLOCKED"
        and any("missing required case id column" in r.lower() for r in val_data.get("reasons", []))
    )
    test_2_4 = {
        "name": "Missing Case Column",
        "description": "Missing ticket_id and case_id column must trigger BLOCKED",
        "status": val_data.get("status"),
        "reasons": val_data.get("reasons"),
        "passed": passed,
    }
    tests.append(test_2_4)
    log(f"Test 2.4 Result: {'PASS' if passed else 'FAIL'} (status: {val_data.get('status')}, reasons: {val_data.get('reasons')})")

    # ------------------------------------------------------------------------
    # Test 2.5: Missing Grain Column (Missing Timestamp Column)
    # ------------------------------------------------------------------------
    log("--- Test 2.5: Missing Timestamp Column ---")
    missing_ts_csv = """ticket_id,status,queue,team,owner,priority,category,sla_deadline,reopen,transfer
T9005,created,Tier1,AlphaTeam,alice,medium,billing,2026-10-10T10:00:00Z,0,0
T9005,completed,Tier1,AlphaTeam,alice,medium,billing,2026-10-10T10:00:00Z,0,0
"""
    r_ref = refresh_csv(missing_ts_csv)
    assert r_ref.status_code == 200
    rev_no_ts = r_ref.json()["dataset_revision"]

    r_val = validate_pilot(revision=rev_no_ts)
    assert r_val.status_code == 200
    val_data = r_val.json()
    passed = (
        val_data.get("status") == "BLOCKED"
        and any("missing required timestamp column" in r.lower() for r in val_data.get("reasons", []))
    )
    test_2_5 = {
        "name": "Missing Timestamp Column",
        "description": "Missing timestamp and created_at column must trigger BLOCKED",
        "status": val_data.get("status"),
        "reasons": val_data.get("reasons"),
        "passed": passed,
    }
    tests.append(test_2_5)
    log(f"Test 2.5 Result: {'PASS' if passed else 'FAIL'} (status: {val_data.get('status')}, reasons: {val_data.get('reasons')})")

    # ------------------------------------------------------------------------
    # Test 2.6: Missing Grain Column (Missing Status / Activity Column)
    # ------------------------------------------------------------------------
    log("--- Test 2.6: Missing Status/Activity Column ---")
    missing_status_csv = """ticket_id,timestamp,queue,team,owner,priority,category,sla_deadline,reopen,transfer
T9006,2026-10-09T10:00:00Z,Tier1,AlphaTeam,alice,medium,billing,2026-10-10T10:00:00Z,0,0
T9006,2026-10-09T11:00:00Z,Tier1,AlphaTeam,alice,medium,billing,2026-10-10T10:00:00Z,0,0
"""
    r_ref = refresh_csv(missing_status_csv)
    assert r_ref.status_code == 200
    rev_no_status = r_ref.json()["dataset_revision"]

    r_val = validate_pilot(revision=rev_no_status)
    assert r_val.status_code == 200
    val_data = r_val.json()
    passed = (
        val_data.get("status") == "BLOCKED"
        and any("missing required status/activity column" in r.lower() for r in val_data.get("reasons", []))
    )
    test_2_6 = {
        "name": "Missing Status/Activity Column",
        "description": "Missing status and activity column must trigger BLOCKED",
        "status": val_data.get("status"),
        "reasons": val_data.get("reasons"),
        "passed": passed,
    }
    tests.append(test_2_6)
    log(f"Test 2.6 Result: {'PASS' if passed else 'FAIL'} (status: {val_data.get('status')}, reasons: {val_data.get('reasons')})")

    # ------------------------------------------------------------------------
    # Test 2.7: Corrupted / Unparseable Timestamps
    # ------------------------------------------------------------------------
    log("--- Test 2.7: Unparseable Timestamps Payload ---")
    unparseable_ts_csv = """ticket_id,created_at,timestamp,status,queue,team,owner,priority,category,sla_deadline,reopen,transfer
T9007,2026-10-09T10:00:00Z,CORRUPTED_NOT_A_DATE,created,Tier1,AlphaTeam,alice,medium,billing,2026-10-10T10:00:00Z,0,0
T9007,2026-10-09T10:00:00Z,2026-99-99T99:99:99Z,completed,Tier1,AlphaTeam,alice,medium,billing,2026-10-10T10:00:00Z,0,0
"""
    r_ref = refresh_csv(unparseable_ts_csv)
    assert r_ref.status_code == 200
    rev_bad_ts = r_ref.json()["dataset_revision"]

    r_val = validate_pilot(revision=rev_bad_ts)
    assert r_val.status_code == 200
    val_data = r_val.json()
    passed = (
        val_data.get("status") == "BLOCKED"
        and any("unparseable or invalid timestamp" in r.lower() for r in val_data.get("reasons", []))
    )
    test_2_7 = {
        "name": "Unparseable Timestamps Payload",
        "description": "Garbage string timestamps must trigger BLOCKED with invalid timestamp count",
        "status": val_data.get("status"),
        "reasons": val_data.get("reasons"),
        "passed": passed,
    }
    tests.append(test_2_7)
    log(f"Test 2.7 Result: {'PASS' if passed else 'FAIL'} (status: {val_data.get('status')}, reasons: {val_data.get('reasons')})")

    # ------------------------------------------------------------------------
    # Test 2.8: Null Values in Required Key Columns
    # ------------------------------------------------------------------------
    log("--- Test 2.8: Null Values in Case ID Payload ---")
    null_case_csv = """ticket_id,created_at,timestamp,status,queue,team,owner,priority,category,sla_deadline,reopen,transfer
,2026-10-09T10:00:00Z,2026-10-09T10:00:00Z,created,Tier1,AlphaTeam,alice,medium,billing,2026-10-10T10:00:00Z,0,0
T9008,2026-10-09T10:00:00Z,2026-10-09T11:00:00Z,completed,Tier1,AlphaTeam,alice,medium,billing,2026-10-10T10:00:00Z,0,0
"""
    r_ref = refresh_csv(null_case_csv)
    assert r_ref.status_code == 200
    rev_null_case = r_ref.json()["dataset_revision"]

    r_val = validate_pilot(revision=rev_null_case)
    assert r_val.status_code == 200
    val_data = r_val.json()
    passed = (
        val_data.get("status") == "BLOCKED"
        and any("null case id" in r.lower() for r in val_data.get("reasons", []))
    )
    test_2_8 = {
        "name": "Null Case ID in Payload",
        "description": "Null case ID rows must trigger BLOCKED",
        "status": val_data.get("status"),
        "reasons": val_data.get("reasons"),
        "passed": passed,
    }
    tests.append(test_2_8)
    log(f"Test 2.8 Result: {'PASS' if passed else 'FAIL'} (status: {val_data.get('status')}, reasons: {val_data.get('reasons')})")

    # ------------------------------------------------------------------------
    # Test 2.9: Non-existent Dataset Revision
    # ------------------------------------------------------------------------
    log("--- Test 2.9: Non-Existent Revision Query ---")
    r_val_missing_rev = validate_pilot(revision=99999)
    assert r_val_missing_rev.status_code == 200
    val_data = r_val_missing_rev.json()
    passed = (
        val_data.get("status") == "BLOCKED"
        and any("not found" in r.lower() for r in val_data.get("reasons", []))
    )
    test_2_9 = {
        "name": "Non-Existent Revision Query",
        "description": "Querying revision 99999 must return status: BLOCKED",
        "status": val_data.get("status"),
        "reasons": val_data.get("reasons"),
        "passed": passed,
    }
    tests.append(test_2_9)
    log(f"Test 2.9 Result: {'PASS' if passed else 'FAIL'} (status: {val_data.get('status')}, reasons: {val_data.get('reasons')})")

    # ------------------------------------------------------------------------
    # Test 2.10: Far-Future Timestamp (Triggering Warnings)
    # ------------------------------------------------------------------------
    log("--- Test 2.10: Far Future Timestamp Payload ---")
    far_future_csv = """ticket_id,created_at,timestamp,status,queue,team,owner,priority,category,sla_deadline,reopen,transfer
T9010,2026-10-09T10:00:00Z,2026-10-09T10:00:00Z,created,Tier1,AlphaTeam,alice,medium,billing,2026-10-10T10:00:00Z,0,0
T9010,2026-10-09T10:00:00Z,2035-01-01T00:00:00Z,completed,Tier1,AlphaTeam,alice,medium,billing,2026-10-10T10:00:00Z,0,0
"""
    r_ref = refresh_csv(far_future_csv)
    assert r_ref.status_code == 200
    rev_future = r_ref.json()["dataset_revision"]

    r_val = validate_pilot(revision=rev_future)
    assert r_val.status_code == 200
    val_data = r_val.json()
    passed = (
        val_data.get("status") == "WARNING"
        and any("far future timestamp" in w.lower() for w in val_data.get("warnings", []))
    )
    test_2_10 = {
        "name": "Far Future Timestamp Warning",
        "description": "Timestamp > 1 year in future should emit WARNING and flag caveat",
        "status": val_data.get("status"),
        "warnings": val_data.get("warnings"),
        "passed": passed,
    }
    tests.append(test_2_10)
    log(f"Test 2.10 Result: {'PASS' if passed else 'FAIL'} (status: {val_data.get('status')}, warnings: {val_data.get('warnings')})")

    results["validation_gate_stress_tests"] = tests
    return tests


# ============================================================================
# Section 3: SQLite Relational Integrity and Edge Cases
# ============================================================================
def challenge_sqlite_integrity() -> list[dict]:
    log("=== Section 3: SQLite Relational Integrity and Constraint Stress Testing ===")
    assert SANDBOX_DB_PATH.exists(), f"Sandbox DB missing: {SANDBOX_DB_PATH}"
    checks = []

    con = sqlite3.connect(str(SANDBOX_DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Pre-test baseline checks
    base_fk = cur.execute("PRAGMA foreign_key_check;").fetchall()
    base_integrity = [r[0] for r in cur.execute("PRAGMA integrity_check;").fetchall()]
    assert len(base_fk) == 0, f"Baseline FK violations exist: {base_fk}"
    assert base_integrity == ["ok"], f"Baseline integrity check failed: {base_integrity}"

    # ------------------------------------------------------------------------
    # Test 3.1: Orphaned Foreign Key Rejection under PRAGMA foreign_keys = ON
    # ------------------------------------------------------------------------
    cur.execute("PRAGMA foreign_keys = ON;")
    fk_status = cur.execute("PRAGMA foreign_keys;").fetchone()[0]
    assert fk_status == 1, "Failed to enable foreign_keys pragma"

    # Attempt to insert decision_evidence_binding referencing non-existent decision
    orphan_error = None
    try:
        cur.execute(
            """
            INSERT INTO decision_evidence_binding (tenant_id, id, decision_id, evidence_id, binding_role, bound_by, bound_at)
            VALUES ('tenant_alpha', 'deb-orphan-01', 'non-existent-dec-999', 'ev-nonexistent', 'primary_support', 'tester', '2026-10-09T00:00:00Z')
            """
        )
        con.commit()
    except sqlite3.IntegrityError as e:
        orphan_error = str(e)
    finally:
        con.rollback()

    passed = orphan_error is not None and "FOREIGN KEY constraint failed" in orphan_error
    check_3_1 = {
        "name": "Orphaned decision_evidence_binding rejection",
        "description": "Direct insert of orphaned foreign key must raise sqlite3.IntegrityError",
        "error_caught": orphan_error,
        "passed": passed,
    }
    checks.append(check_3_1)
    log(f"Check 3.1 Result: {'PASS' if passed else 'FAIL'} (caught: {orphan_error})")

    # Attempt to insert dataset_revision referencing non-existent dataset
    orphan_ds_error = None
    try:
        cur.execute(
            """
            INSERT INTO dataset_revision (tenant_id, dataset_id, revision, state, manifest, row_count, created_at)
            VALUES ('tenant_alpha', 'non-existent-dataset-xyz', 1, 'published', '{}', 1, '2026-10-09T00:00:00Z')
            """
        )
        con.commit()
    except sqlite3.IntegrityError as e:
        orphan_ds_error = str(e)
    finally:
        con.rollback()

    passed_ds = orphan_ds_error is not None and "FOREIGN KEY constraint failed" in orphan_ds_error
    check_3_1b = {
        "name": "Orphaned dataset_revision rejection",
        "description": "Insert into dataset_revision with non-existent dataset_id must raise FOREIGN KEY constraint failed",
        "error_caught": orphan_ds_error,
        "passed": passed_ds,
    }
    checks.append(check_3_1b)
    log(f"Check 3.1b Result: {'PASS' if passed_ds else 'FAIL'} (caught: {orphan_ds_error})")

    # Attempt to insert predictive_model referencing non-existent target
    orphan_mod_error = None
    try:
        cur.execute(
            """
            INSERT INTO predictive_model (tenant_id, id, target_id, version, model_kind, algorithm, feature_contract_json, training_dataset_revision, training_time_range_json, evaluation_time_range_json, checksum, created_by, created_at)
            VALUES ('tenant_alpha', 'mdl-orphan-01', 'tgt-non-existent-999', 1, 'classification_risk', 'LR', '{}', 1, '{}', '{}', 'chk', 'tester', '2026-10-09T00:00:00Z')
            """
        )
        con.commit()
    except sqlite3.IntegrityError as e:
        orphan_mod_error = str(e)
    finally:
        con.rollback()

    passed_mod = orphan_mod_error is not None and "FOREIGN KEY constraint failed" in orphan_mod_error
    check_3_1c = {
        "name": "Orphaned predictive_model rejection",
        "description": "Insert into predictive_model with non-existent target_id must raise FOREIGN KEY constraint failed",
        "error_caught": orphan_mod_error,
        "passed": passed_mod,
    }
    checks.append(check_3_1c)
    log(f"Check 3.1c Result: {'PASS' if passed_mod else 'FAIL'} (caught: {orphan_mod_error})")

    # ------------------------------------------------------------------------
    # Test 3.2: Conflicting Inserts / Unique Constraint Violations
    # ------------------------------------------------------------------------
    # Fetch an existing decision from database or seed one
    existing_dec = cur.execute("SELECT tenant_id, id FROM decision LIMIT 1").fetchone()
    if existing_dec is None:
        cur.execute(
            """
            INSERT INTO decision (tenant_id, id, title, brief_json, created_by, created_at, updated_at)
            VALUES ('tenant_alpha', 'dec-seed-01', 'Baseline Seed Decision', '{}', 'tester', '2026-10-09T00:00:00Z', '2026-10-09T00:00:00Z')
            """
        )
        con.commit()
        existing_dec = cur.execute("SELECT tenant_id, id FROM decision LIMIT 1").fetchone()
    e_tenant, e_dec_id = existing_dec["tenant_id"], existing_dec["id"]

    duplicate_dec_error = None
    try:
        cur.execute(
            """
            INSERT INTO decision (tenant_id, id, title, brief_json, created_by, created_at, updated_at)
            VALUES (?, ?, 'Duplicate Conflict Decision', '{}', 'tester', '2026-10-09T00:00:00Z', '2026-10-09T00:00:00Z')
            """,
            (e_tenant, e_dec_id),
        )
        con.commit()
    except sqlite3.IntegrityError as e:
        duplicate_dec_error = str(e)
    finally:
        con.rollback()

    passed_dup_dec = duplicate_dec_error is not None and "UNIQUE constraint failed" in duplicate_dec_error
    check_3_2a = {
        "name": "Conflicting decision insert rejection",
        "description": "Duplicate (tenant_id, id) in decision must raise UNIQUE constraint failed",
        "error_caught": duplicate_dec_error,
        "passed": passed_dup_dec,
    }
    checks.append(check_3_2a)
    log(f"Check 3.2a Result: {'PASS' if passed_dup_dec else 'FAIL'} (caught: {duplicate_dec_error})")

    # Fetch existing dataset_revision
    existing_rev = cur.execute("SELECT tenant_id, dataset_id, revision FROM dataset_revision LIMIT 1").fetchone()
    dup_rev_error = None
    try:
        cur.execute(
            """
            INSERT INTO dataset_revision (tenant_id, dataset_id, revision, state, manifest, row_count, created_at)
            VALUES (?, ?, ?, 'published', '{}', 1, '2026-10-09T00:00:00Z')
            """,
            (existing_rev["tenant_id"], existing_rev["dataset_id"], existing_rev["revision"]),
        )
        con.commit()
    except sqlite3.IntegrityError as e:
        dup_rev_error = str(e)
    finally:
        con.rollback()

    passed_dup_rev = dup_rev_error is not None and "UNIQUE constraint failed" in dup_rev_error
    check_3_2b = {
        "name": "Conflicting dataset_revision insert rejection",
        "description": "Duplicate (tenant_id, dataset_id, revision) must raise UNIQUE constraint failed",
        "error_caught": dup_rev_error,
        "passed": passed_dup_rev,
    }
    checks.append(check_3_2b)
    log(f"Check 3.2b Result: {'PASS' if passed_dup_rev else 'FAIL'} (caught: {dup_rev_error})")

    # ------------------------------------------------------------------------
    # Test 3.3: Verification of PRAGMA foreign_key_check Oracle Detection
    # ------------------------------------------------------------------------
    # Temporarily bypass FK pragma within an isolated transaction to verify that
    # PRAGMA foreign_key_check actually detects intentional orphans!
    cur.execute("PRAGMA foreign_keys = OFF;")
    cur.execute("BEGIN TRANSACTION;")
    cur.execute(
        """
        INSERT INTO decision_evidence_binding (tenant_id, id, decision_id, evidence_id, binding_role, bound_by, bound_at)
        VALUES ('tenant_alpha', 'deb-forced-orphan', 'fake-decision-id', 'fake-evidence-id', 'primary_support', 'tester', '2026-10-09T00:00:00Z')
        """
    )
    detected_violations = cur.execute("PRAGMA foreign_key_check(decision_evidence_binding);").fetchall()
    con.rollback()
    cur.execute("PRAGMA foreign_keys = ON;")

    oracle_passed = len(detected_violations) > 0 and any(r[0] == "decision_evidence_binding" for r in detected_violations)
    check_3_3 = {
        "name": "PRAGMA foreign_key_check Oracle Verification",
        "description": "Forced orphaned row must be immediately caught by PRAGMA foreign_key_check",
        "violations_detected": len(detected_violations),
        "details": [dict(r) if hasattr(r, 'keys') else list(r) for r in detected_violations],
        "passed": oracle_passed,
    }
    checks.append(check_3_3)
    log(f"Check 3.3 Result: {'PASS' if oracle_passed else 'FAIL'} (detected violations: {len(detected_violations)})")

    # ------------------------------------------------------------------------
    # Test 3.4: Final Clean State Integrity Certification
    # ------------------------------------------------------------------------
    post_fk = cur.execute("PRAGMA foreign_key_check;").fetchall()
    post_integrity = [r[0] for r in cur.execute("PRAGMA integrity_check;").fetchall()]
    clean_passed = (len(post_fk) == 0) and (post_integrity == ["ok"])
    check_3_4 = {
        "name": "Post-Stress SQLite Relational Clean State Certification",
        "description": "Post-stress PRAGMA foreign_key_check must be [] and PRAGMA integrity_check must be ['ok']",
        "fk_check": [list(r) for r in post_fk],
        "integrity_check": post_integrity,
        "passed": clean_passed,
    }
    checks.append(check_3_4)
    log(f"Check 3.4 Result: {'PASS' if clean_passed else 'FAIL'} (FK: {post_fk}, Integrity: {post_integrity})")

    con.close()
    results["sqlite_relational_integrity"] = checks
    return checks


# ============================================================================
# Main Orchestrator
# ============================================================================
def main():
    log("Starting Milestone 1 Empirical Adversarial Challenge Battery...")
    t0 = time.perf_counter()

    # 1. Dataset audit
    audit_res = audit_synthetic_dataset()

    # 2. Validation gate stress testing
    with httpx.Client(timeout=30.0) as client:
        gate_res = stress_test_validation_gate(client)

    # 3. SQLite relational integrity challenge
    sqlite_res = challenge_sqlite_integrity()

    elapsed = time.perf_counter() - t0

    # Evaluate verdict
    all_gate_passed = all(t["passed"] for t in gate_res)
    audit_passed = audit_res["verdict"] == "PASS"
    all_sqlite_passed = all(c["passed"] for c in sqlite_res)

    verdict = "APPROVE" if (all_gate_passed and audit_passed and all_sqlite_passed) else "REJECT"
    results["overall_verdict"] = verdict
    results["elapsed_seconds"] = round(elapsed, 2)

    log("============================================================================")
    log(f"EMPIRICAL CHALLENGE BATTERY COMPLETED IN {elapsed:.2f}s")
    log(f"Synthetic Dataset Audit: {'PASS' if audit_passed else 'FAIL'}")
    log(f"Validation Gate Stress Tests: {sum(t['passed'] for t in gate_res)}/{len(gate_res)} PASSED")
    log(f"SQLite Relational Integrity Checks: {sum(c['passed'] for c in sqlite_res)}/{len(sqlite_res)} PASSED")
    log(f"OVERALL VERDICT: {verdict}")
    log("============================================================================")

    # Write summary artifact
    out_path = Path("var/qa_artifacts/milestone1_adversarial_challenge_results.json")
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    log(f"Detailed challenge results saved to {out_path}")

    if verdict != "APPROVE":
        sys.exit(1)


if __name__ == "__main__":
    main()
