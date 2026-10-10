"""
scripts/run_phase1_ingestion.py
DecisionOS PILOT-01 Milestone 1: Phase 1 Synthetic Ingestion, Auth Boundary & Metric Refresh Runner.

Executes:
1. Authentication boundary verification (401 on synthetic test headers, 404 on cross-tenant spoofing).
2. Synthetic 50-ticket batch CSV generation (138 event rows) matching the 12-column golden support schema.
3. Pilot contract bootstrap and baseline KPI capture.
4. Pilot dataset ingestion via POST /v1/pilots/{id}/refresh.
5. Pilot data readiness validation via POST /v1/pilots/{id}/validate-data (status: PASS).
6. Real-time dynamic KPI metric update verification without service restart.
7. Saves raw artifacts: var/qa_artifacts/synthetic_50_tickets.csv & var/qa_artifacts/phase1_ingestion_summary.json.
"""

import io
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import polars as pl

API_BASE_URL = "http://localhost:8100/v1"
SANDBOX_DIR = Path("var/sandbox_pilot01")
SANDBOX_DB = SANDBOX_DIR / "control.sqlite3"
ARTIFACTS_DIR = Path("var/qa_artifacts")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

CSV_ARTIFACT_PATH = ARTIFACTS_DIR / "synthetic_50_tickets.csv"
SUMMARY_ARTIFACT_PATH = ARTIFACTS_DIR / "phase1_ingestion_summary.json"

AUTH_TEST_HEADERS = {"X-Tenant": "test-tenant", "X-User": "qa-operator"}
AUTH_CROSS_HEADERS = {"X-Tenant": "tenant_beta", "X-User": "alpha.manager"}
ALPHA_HEADERS = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def verify_auth_boundaries(client: httpx.Client) -> dict:
    log("=== Step 1: Testing Authentication Boundary Behavior ===")
    results = {}

    # 1. Synthetic headers on /v1/pilots
    r1 = client.get(f"{API_BASE_URL}/pilots", headers=AUTH_TEST_HEADERS)
    log(f"GET /v1/pilots with test-tenant/qa-operator -> HTTP {r1.status_code}")
    assert r1.status_code == 401, f"Expected 401, got {r1.status_code}"
    r1_json = r1.json()
    assert "demo authentication missing" in r1_json.get("detail", ""), f"Unexpected detail: {r1_json}"
    results["pilots_auth_guard"] = {
        "status_code": r1.status_code,
        "detail": r1_json.get("detail"),
        "passed": True,
    }

    # 2. Synthetic headers on /v1/uploads
    r2 = client.post(
        f"{API_BASE_URL}/uploads",
        headers=AUTH_TEST_HEADERS,
        json={"filename": "test.csv", "workspace_id": "ws-support-ops", "size_bytes": 1024},
    )
    log(f"POST /v1/uploads with test-tenant/qa-operator -> HTTP {r2.status_code}")
    assert r2.status_code == 401, f"Expected 401, got {r2.status_code}"
    r2_json = r2.json()
    assert "demo authentication missing" in r2_json.get("detail", ""), f"Unexpected detail: {r2_json}"
    results["uploads_auth_guard"] = {
        "status_code": r2.status_code,
        "detail": r2_json.get("detail"),
        "passed": True,
    }

    # 3. Cross-tenant isolation spoofing
    r3 = client.get(f"{API_BASE_URL}/pilots", headers=AUTH_CROSS_HEADERS)
    log(f"GET /v1/pilots with tenant_beta/alpha.manager -> HTTP {r3.status_code}")
    assert r3.status_code == 404, f"Expected 404, got {r3.status_code}"
    r3_json = r3.json()
    assert "not found" in r3_json.get("detail", ""), f"Unexpected detail: {r3_json}"
    results["cross_tenant_isolation_guard"] = {
        "status_code": r3.status_code,
        "detail": r3_json.get("detail"),
        "passed": True,
    }

    log("[SUCCESS] Authentication boundaries verified (401 demo missing & 404 cross-tenant isolation).")
    return results


def generate_synthetic_50_tickets() -> str:
    log("=== Step 2: Generating Synthetic 50-Ticket Batch (138 Rows) ===")
    base_time = datetime(2026, 10, 8, 8, 0, 0, tzinfo=timezone.utc)
    queues = ["Tier1", "Tier2", "Escalations"]
    teams = ["AlphaTeam", "BetaTeam"]
    owners = ["alice", "bob", "charlie", "david", "eve"]
    priorities = ["low", "medium", "high", "critical"]
    categories = ["billing", "technical", "general", "security", "outage"]

    rows = []
    # Total tickets = 50. Total event rows = 138:
    # 39 tickets * 3 rows = 117
    # 10 tickets * 2 rows = 20
    # 1 ticket * 1 row = 1
    # 117 + 20 + 1 = 138 rows
    for i in range(1, 51):
        tid = f"T{1000 + i}"
        t0 = base_time + timedelta(minutes=i * 12)
        t0_iso = t0.strftime("%Y-%m-%dT%H:%M:%SZ")
        sla = (t0 + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        q = queues[i % len(queues)]
        tm = teams[i % len(teams)]
        ow = owners[i % len(owners)]
        pr = priorities[i % len(priorities)]
        cat = categories[i % len(categories)]

        if i <= 39:
            # Standard resolution lifecycle: created -> in_progress -> completed
            t1 = (t0 + timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
            t2 = (t0 + timedelta(hours=3, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
            rows.append({
                "ticket_id": tid, "created_at": t0_iso, "timestamp": t0_iso, "status": "created",
                "queue": q, "team": tm, "owner": ow, "priority": pr, "category": cat,
                "sla_deadline": sla, "reopen": 0, "transfer": 0,
            })
            rows.append({
                "ticket_id": tid, "created_at": t0_iso, "timestamp": t1, "status": "in_progress",
                "queue": q, "team": tm, "owner": ow, "priority": pr, "category": cat,
                "sla_deadline": sla, "reopen": 0, "transfer": 0,
            })
            rows.append({
                "ticket_id": tid, "created_at": t0_iso, "timestamp": t2, "status": "completed",
                "queue": q, "team": tm, "owner": ow, "priority": pr, "category": cat,
                "sla_deadline": sla, "reopen": 0, "transfer": 0,
            })
        elif i <= 49:
            # Active unresolved lifecycle: created -> in_progress
            t1 = (t0 + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
            rows.append({
                "ticket_id": tid, "created_at": t0_iso, "timestamp": t0_iso, "status": "created",
                "queue": q, "team": tm, "owner": ow, "priority": pr, "category": cat,
                "sla_deadline": sla, "reopen": 0, "transfer": 0,
            })
            rows.append({
                "ticket_id": tid, "created_at": t0_iso, "timestamp": t1, "status": "in_progress",
                "queue": q, "team": tm, "owner": ow, "priority": pr, "category": cat,
                "sla_deadline": sla, "reopen": 0, "transfer": 1,
            })
        else:
            # Newly created open ticket: created
            rows.append({
                "ticket_id": tid, "created_at": t0_iso, "timestamp": t0_iso, "status": "created",
                "queue": q, "team": tm, "owner": ow, "priority": pr, "category": cat,
                "sla_deadline": sla, "reopen": 0, "transfer": 0,
            })

    df = pl.DataFrame(rows)
    assert df.height == 138, f"Expected 138 rows, got {df.height}"
    assert df["ticket_id"].n_unique() == 50, f"Expected 50 unique cases, got {df['ticket_id'].n_unique()}"

    csv_buf = io.StringIO()
    df.write_csv(csv_buf)
    csv_text = csv_buf.getvalue()

    CSV_ARTIFACT_PATH.write_text(csv_text, encoding="utf-8")
    log(f"Generated synthetic CSV ({df.height} rows, {df['ticket_id'].n_unique()} cases). Saved to {CSV_ARTIFACT_PATH}")
    return csv_text


def ensure_pilot_and_dataset(client: httpx.Client) -> tuple[dict, str, str]:
    log("=== Step 3: Bootstrapping Pilot Infrastructure ===")
    dataset_id = "ds-support-ops"

    # Ensure dataset entry exists in sandbox SQLite database
    con = sqlite3.connect(str(SANDBOX_DB))
    cur = con.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO dataset (tenant_id, id, workspace_id, name, published_revision, created_at)
        VALUES ('tenant_alpha', ?, 'ws-support-ops', 'Support Operations Golden Dataset', 1, '2026-10-08T00:00:00Z')
        """,
        (dataset_id,),
    )
    con.commit()
    con.close()

    # Call bootstrap API
    boot_res = client.post(
        f"{API_BASE_URL}/pilots/bootstrap",
        headers=ALPHA_HEADERS,
        json={
            "name": "Golden Support Operations Pilot",
            "domain": "support_ticket_operations",
            "owner": "alpha.manager",
            "dataset_id": dataset_id,
            "dataset_revision": 1,
        },
    )
    assert boot_res.status_code == 201, f"Bootstrap failed with {boot_res.status_code}: {boot_res.text}"
    boot_data = boot_res.json()
    pilot = boot_data["pilot"]
    target_id = boot_data["target"]["id"]
    model_id = boot_data["model"]["id"]

    log(f"Pilot bootstrapped: id={pilot['id']} name='{pilot['name']}' status={pilot['status']} model_id={model_id}")
    return pilot, dataset_id, model_id


def run():
    log("Starting Milestone 1 Phase 1 Ingestion and Verification...")
    summary_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "Milestone 1: Phase 1 — Interactive Smoke Test & Empty-State Validation + API Ingestion",
    }

    with httpx.Client(timeout=30.0) as client:
        # Pre-flight health
        health_res = client.get(f"{API_BASE_URL}/health")
        assert health_res.status_code == 200, f"API health failed: {health_res.text}"
        log("Backend pre-flight health confirmed.")

        # 1. Auth boundaries
        auth_results = verify_auth_boundaries(client)
        summary_data["auth_boundaries"] = auth_results

        # 2. Synthetic 50 tickets CSV
        csv_text = generate_synthetic_50_tickets()
        summary_data["synthetic_dataset"] = {
            "artifact_path": str(CSV_ARTIFACT_PATH),
            "total_rows": 138,
            "unique_cases": 50,
            "columns": 12,
        }

        # 3. Pilot bootstrap
        pilot, dataset_id, model_id = ensure_pilot_and_dataset(client)
        pilot_id = pilot["id"]
        summary_data["pilot"] = {
            "id": pilot_id,
            "name": pilot["name"],
            "dataset_id": dataset_id,
            "initial_status": pilot["status"],
        }

        # 4. Capture baseline summary
        base_sum_res = client.get(f"{API_BASE_URL}/pilots/{pilot_id}/summary", headers=ALPHA_HEADERS)
        assert base_sum_res.status_code == 200
        baseline_summary = base_sum_res.json()["summary"]
        log(f"Baseline Pilot Summary: {baseline_summary}")
        summary_data["baseline_summary"] = baseline_summary

        # 5. Ingest 50-ticket batch via POST /v1/pilots/{id}/refresh
        log("=== Step 4: Refreshing Pilot Dataset (Ingesting 50 Tickets) ===")
        t_start = time.perf_counter()
        refresh_res = client.post(
            f"{API_BASE_URL}/pilots/{pilot_id}/refresh",
            headers=ALPHA_HEADERS,
            json={"dataset_id": dataset_id, "csv_content": csv_text},
        )
        refresh_latency_ms = (time.perf_counter() - t_start) * 1000.0
        assert refresh_res.status_code == 200, f"Refresh failed ({refresh_res.status_code}): {refresh_res.text}"
        refreshed_pilot = refresh_res.json()
        log(f"Refresh completed in {refresh_latency_ms:.2f}ms. Bumped dataset_revision to {refreshed_pilot.get('dataset_revision')}")
        summary_data["ingestion"] = {
            "status_code": refresh_res.status_code,
            "latency_ms": round(refresh_latency_ms, 2),
            "dataset_revision": refreshed_pilot.get("dataset_revision"),
            "passed": True,
        }

        # 6. Validate Data Readiness Gate
        log("=== Step 5: Validating Data Readiness Gate ===")
        val_res = client.post(
            f"{API_BASE_URL}/pilots/{pilot_id}/validate-data",
            headers=ALPHA_HEADERS,
            json={"dataset_id": dataset_id, "dataset_revision": refreshed_pilot.get("dataset_revision")},
        )
        assert val_res.status_code == 200, f"Validate-data failed: {val_res.text}"
        val_data = val_res.json()
        log(f"Quality Gate Response: status={val_data.get('status')} metrics={val_data.get('metrics')}")
        assert val_data.get("status") == "PASS", f"Expected PASS, got {val_data}"
        assert len(val_data.get("reasons", [])) == 0
        summary_data["data_readiness_validation"] = {
            "status": val_data.get("status"),
            "reasons": val_data.get("reasons"),
            "warnings": val_data.get("warnings"),
            "metrics": val_data.get("metrics"),
            "passed": True,
        }

        # 7. Verify dynamic metric updates without restart
        log("=== Step 6: Verifying Dynamic KPI Metric Updates (Zero Restart) ===")
        # a. Create a decision
        dec_res = client.post(
            f"{API_BASE_URL}/decisions",
            headers=ALPHA_HEADERS,
            json={
                "title": "Dynamic Triage Capacity Expansion",
                "brief": {
                    "problem": "Ticket surge observed in Tier-2 technical queue",
                    "relevant_findings": ["Predictive risk score indicates elevated SLA breach potential"],
                    "proposed_action": "Reassign Tier-1 support leads to technical escalation queue",
                    "baseline_option": "Status quo staffing",
                    "scope": "Support Operations",
                    "owner": "alpha.manager",
                    "trade_offs": ["Minor buffer reduction in Tier-1 triage"],
                    "assumptions": ["Escalation volume stabilizes within 24h"],
                    "evidence_coverage": ["pred_artifact_001"],
                    "validation_plan": "14-day outcome review",
                    "counter_metrics": ["reopen_rate"],
                    "expected_effect": "estimated",
                },
            },
        )
        assert dec_res.status_code == 201, f"Decision creation failed: {dec_res.text}"
        dec_id = dec_res.json()["id"]
        log(f"Created decision: id={dec_id}")

        # b. Transition predictive model to active status
        for st in ["evaluated", "approved", "active"]:
            tr_res = client.post(
                f"{API_BASE_URL}/predictive/models/{model_id}/transition",
                headers=ALPHA_HEADERS,
                json={"status": st},
            )
            assert tr_res.status_code == 200, f"Transition to {st} failed: {tr_res.text}"
        log(f"Model {model_id} transitioned through evaluated -> approved -> active.")

        # c. Score a predictive high-risk case
        # T1040 is an open in_progress ticket with deadline 24h from creation
        t40_deadline = (datetime(2026, 10, 8, 8, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=40 * 12 + 24 * 60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        score_res = client.post(
            f"{API_BASE_URL}/predictive/score",
            headers=ALPHA_HEADERS,
            json={
                "model_id": model_id,
                "case_id": "T1040",
                "observation_time": "2026-10-09T08:00:00Z",
                "deadline": t40_deadline,
                "current_status": "in_progress",
                "features": {"case_age_hours": 12.0},
            },
        )
        assert score_res.status_code == 200, f"Predictive scoring failed: {score_res.text}"
        score_data = score_res.json()
        log(f"Scored case T1040: risk_tier={score_data.get('risk_tier')} score={score_data.get('score')}")
        assert score_data.get("risk_tier") == "HIGH", f"Expected HIGH risk tier, got {score_data}"

        # c. Record an active alert episode directly into sandbox SQLite
        con = sqlite3.connect(str(SANDBOX_DB))
        cur = con.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO alert_episode (
                tenant_id, id, rule_id, episode_identity, condition_id,
                workflow_status, observed_value, expected_lower, expected_upper,
                started_at, resolved_at
            ) VALUES (
                'tenant_alpha', 'ep-alpha-001', 'rule-sla-breach', 'ep-ident-001', 'cond-001',
                'open', 0.28, 0.05, 0.15,
                '2026-10-09T18:00:00Z', NULL
            )
            """
        )
        con.commit()
        con.close()
        log("Inserted active alert episode ep-alpha-001 into sandbox SQLite.")

        # d. Query GET /v1/pilots/{id}/summary without service restart
        post_sum_res = client.get(f"{API_BASE_URL}/pilots/{pilot_id}/summary", headers=ALPHA_HEADERS)
        assert post_sum_res.status_code == 200, f"Summary failed: {post_sum_res.text}"
        post_summary = post_sum_res.json()["summary"]
        log(f"Refreshed Command Center Summary: {post_summary}")

        assert post_summary["open_alerts"] >= 1, f"Expected open_alerts >= 1, got {post_summary['open_alerts']}"
        assert post_summary["high_risk_cases"] >= 1, f"Expected high_risk_cases >= 1, got {post_summary['high_risk_cases']}"
        assert post_summary["open_decisions"] >= 1, f"Expected open_decisions >= 1, got {post_summary['open_decisions']}"
        assert post_summary["data_readiness"] == "PASS", f"Expected data_readiness PASS, got {post_summary['data_readiness']}"

        summary_data["dynamic_kpi_verification"] = {
            "baseline": baseline_summary,
            "refreshed": post_summary,
            "open_alerts_delta": post_summary["open_alerts"] - baseline_summary["open_alerts"],
            "high_risk_cases_delta": post_summary["high_risk_cases"] - baseline_summary["high_risk_cases"],
            "open_decisions_delta": post_summary["open_decisions"] - baseline_summary["open_decisions"],
            "data_readiness": post_summary["data_readiness"],
            "zero_restart_verified": True,
            "passed": True,
        }

    # Save summary artifact
    SUMMARY_ARTIFACT_PATH.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")
    log(f"=== Execution Summary saved to {SUMMARY_ARTIFACT_PATH} ===")
    log("[SUCCESS] Milestone 1 Phase 1 Ingestion and Dynamic Refresh verified successfully!")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        log(f"[FATAL ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
