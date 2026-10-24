#!/usr/bin/env python3
"""Cold-start the DecisionOS demo through the public HTTP contract.

Creates (only when missing) a published dataset, an approved metric, a
monitoring rule, and three decisions in draft/proposed/active states. Uses only
the running API: no direct database writes. Safe to re-run.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

DATASET_FILENAME = "demo_support_tickets.csv"
METRIC_ID = "metric-demo-first-response-rate"
METRIC_NAME = "Demo first response rate"
RULE_NAME = "Demo: first response rate drop"
WINDOW = {
    "start": "2026-01-01T00:00:00Z",
    "end": "2026-04-01T00:00:00Z",
    "timezone": "Asia/Bahrain",
}

CSV_CONTENT = """case_id,subject,priority,channel,originating_branch,status,created_at,first_response_at,resolved_at,reopen_count,customer_id
DEMO-001,Router configuration help,normal,email,MAN-02,open,2026-01-05T02:36:23Z,2026-01-05T07:53:07Z,,0,C00001
DEMO-002,Change data plan,urgent,web,MAN-02,resolved,2026-01-16T19:59:48Z,2026-01-16T23:11:28Z,2026-01-17T06:27:47Z,0,C00002
DEMO-003,No mobile signal,high,phone,MAN-01,open,2026-01-21T08:10:00Z,2026-01-22T09:00:00Z,,1,C00003
DEMO-004,Billing question,normal,email,MAN-01,resolved,2026-02-02T10:00:00Z,2026-02-02T11:30:00Z,2026-02-03T12:00:00Z,0,C00004
DEMO-005,Slow internet at peak,high,web,RUH-01,open,2026-02-07T14:20:00Z,,,2,C00005
DEMO-006,Request new SIM,low,email,RUH-01,resolved,2026-02-11T09:45:00Z,2026-02-11T12:05:00Z,2026-02-12T08:00:00Z,0,C00006
DEMO-007,Cannot send SMS,high,phone,MAN-02,resolved,2026-02-18T16:30:00Z,2026-02-18T18:10:00Z,2026-02-19T10:00:00Z,0,C00007
DEMO-008,Duplicate charge,urgent,web,MAN-01,open,2026-03-01T07:15:00Z,2026-03-01T08:00:00Z,,0,C00008
DEMO-009,Voicemail not working,normal,email,RUH-01,resolved,2026-03-04T11:00:00Z,2026-03-05T10:00:00Z,2026-03-06T09:00:00Z,1,C00009
DEMO-010,Roaming charges,high,phone,MAN-02,open,2026-03-08T17:40:00Z,,,0,C00010
"""

DECISION_BRIEF = {
    "problem": "First response times vary by branch and may breach the service target.",
    "relevant_findings": ["Some tickets are still unanswered after the first contact window."],
    "proposed_action": "Rebalance queue staffing toward the slowest branch for two weeks.",
    "baseline_option": "Keep the current staffing roster unchanged.",
    "scope": "Support operations, tenant_alpha, demo dataset.",
    "owner": "alpha.manager",
    "trade_offs": ["Short-term overtime cost versus faster response."],
    "assumptions": ["Ticket volume stays within the observed range."],
    "evidence_coverage": ["Published demo dataset and approved first-response metric."],
    "validation_plan": "Compare first response rate and median response time after two weeks.",
    "counter_metrics": ["cost_per_ticket", "agent_utilization"],
    "expected_effect": "estimated",
}

DECISION_TARGETS = (
    ("Demo: draft - first response staffing review", "draft"),
    ("Demo: proposed - first response staffing review", "proposed"),
    ("Demo: active - first response staffing review", "active"),
)

DECISION_PATH = ["draft", "proposed", "accepted", "active"]


class SeedError(RuntimeError):
    pass


class Api:
    def __init__(self, base_url: str, tenant: str, user: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.tenant = tenant
        self.user = user

    def call(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        raw_body: bytes | None = None,
        user: str | None = None,
        expected: tuple[int, ...] = (200,),
    ):
        headers = {
            "Accept": "application/json",
            "X-Tenant": self.tenant,
            "X-User": user or self.user,
        }
        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif raw_body is not None:
            data = raw_body
            headers["Content-Type"] = "text/csv"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                payload = response.read()
        except urllib.error.HTTPError as err:
            status = err.code
            payload = err.read()
        except urllib.error.URLError as err:
            raise SeedError(f"{method} {path} failed: {err}") from err

        if status not in expected:
            detail = payload.decode("utf-8", errors="replace")[:500]
            raise SeedError(f"{method} {path} -> HTTP {status}: {detail}")
        if not payload:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError as err:
            raise SeedError(f"{method} {path} returned non-JSON: {payload[:200]!r}") from err


def modeler_for(tenant: str) -> str:
    prefix = tenant.removeprefix("tenant_") if tenant.startswith("tenant_") else tenant
    return f"{prefix}.modeler"


def ensure_dataset(api: Api, modeler: str, summary: list[str]) -> str:
    datasets = api.call("GET", "/datasets?limit=500")
    existing = next((d for d in datasets if d["name"] == DATASET_FILENAME), None)
    if existing is not None:
        dataset_id = existing["dataset_id"]
        if existing["grain_confirmed"] and existing["revision"] is not None:
            summary.append(f"dataset: skipped ({DATASET_FILENAME})")
            return dataset_id

        if not existing["grain_confirmed"]:
            candidates = api.call("GET", f"/datasets/{dataset_id}/grain-candidates")
            candidate = next((c for c in candidates if c["key_columns"] == ["case_id"]), None)
            if candidate is None or not candidate["unique_over_full_data"]:
                raise SeedError("existing demo dataset has no provable case_id grain")
            api.call(
                "POST",
                f"/datasets/{dataset_id}/grain-confirmation",
                json_body={"key_columns": ["case_id"]},
            )
        if existing["revision"] is None:
            if existing["latest_revision"] is None:
                raise SeedError("existing demo dataset has no revision to publish")
            api.call(
                "POST",
                f"/datasets/{dataset_id}/revisions/{existing['latest_revision']}/publish",
            )
        summary.append(f"dataset: repaired ({DATASET_FILENAME})")
        return dataset_id

    body = CSV_CONTENT.encode("utf-8")
    upload = api.call(
        "POST",
        "/uploads",
        json_body={
            "filename": DATASET_FILENAME,
            "size_bytes": len(body),
            "workspace_id": "ws-support-ops",
        },
        expected=(201,),
    )
    upload_id = upload["upload_id"]
    api.call("PUT", f"/uploads/{upload_id}/content", raw_body=body)
    finalized = api.call("POST", f"/uploads/{upload_id}/finalize")
    if finalized.get("status") == "rejected":
        raise SeedError(f"upload rejected: {finalized.get('scan')}")
    dataset_id = finalized["dataset_id"]
    revision = finalized["revision"]

    candidates = api.call("GET", f"/uploads/{upload_id}/grain-candidates")
    candidate = next((c for c in candidates if c["key_columns"] == ["case_id"]), None)
    if candidate is None or not candidate["unique_over_full_data"]:
        raise SeedError("case_id does not uniquely identify demo rows")
    api.call(
        "POST",
        f"/datasets/{dataset_id}/grain-confirmation",
        json_body={"key_columns": ["case_id"]},
    )
    published = api.call("POST", f"/datasets/{dataset_id}/revisions/{revision}/publish")
    if published.get("status") != "published":
        raise SeedError(f"publish did not complete: {published}")
    summary.append(f"dataset: created ({DATASET_FILENAME}, revision {revision})")
    return dataset_id


def ensure_metric(api: Api, modeler: str, dataset_id: str, summary: list[str]) -> None:
    definitions = api.call("GET", "/metrics/definitions?limit=500")
    mine = [d for d in definitions if d["metric_id"] == METRIC_ID]
    if any(d["status"] == "approved" for d in mine):
        summary.append(f"metric: skipped ({METRIC_ID})")
        return

    if mine:
        version = max(d["version"] for d in mine)
    else:
        definition = {
            "metric_id": METRIC_ID,
            "name": METRIC_NAME,
            "kind": "ratio",
            "expression": {
                "kind": "ratio",
                "numerator_predicates": [{"op": "is_not_null", "field": "first_response_at"}],
                "denominator_predicates": [],
            },
            "eligibility": [{"op": "not_in", "field": "status", "value": ["spam"]}],
            "time_basis": "created_at",
            "timezone": "Asia/Bahrain",
            "dataset_id": dataset_id,
        }
        proposed = api.call("POST", "/metrics/definitions", json_body=definition, user=modeler, expected=(201,))
        version = proposed["version"]

    api.call(
        "POST",
        f"/metrics/definitions/{METRIC_ID}/approve",
        json_body={
            "version": version,
            "change_reason": "Cold-start demo approval",
            "semantic_release_id": "release-demo",
        },
    )
    summary.append(f"metric: created and approved ({METRIC_ID} v{version})")


def ensure_query(api: Api, summary: list[str]) -> None:
    result = api.call(
        "POST",
        "/metrics/query",
        json_body={
            "schema_version": "1.0",
            "metric_id": METRIC_ID,
            "dimensions": ["originating_branch"],
            "filters": [],
            "window": WINDOW,
            "limit": 100,
        },
    )
    if result.get("status") != "answered" or not result.get("rows"):
        raise SeedError(f"certified metric query did not return data: {result}")
    summary.append(f"metric query: answered ({result['row_count']} rows)")


def ensure_monitoring_rule(api: Api, dataset_id: str, summary: list[str]) -> None:
    payload = api.call("GET", "/monitoring/rules?limit=500")
    rules = payload.get("rules", [])
    if any(rule["name"] == RULE_NAME for rule in rules):
        summary.append(f"monitoring rule: skipped ({RULE_NAME})")
        return
    api.call(
        "POST",
        "/monitoring/rules",
        json_body={
            "name": RULE_NAME,
            "dataset_id": dataset_id,
            "metric_id": METRIC_ID,
            "method": "seasonal_naive",
            "season_length": 7,
            "threshold": 3.0,
            "min_effect_size": 0.01,
            "persistence": 1,
            "owner": api.user,
            "escalation": "Support operations lead",
            "runbook": "Check queue staffing, then rerun the certified metric query.",
        },
        expected=(201,),
    )
    summary.append(f"monitoring rule: created ({RULE_NAME})")


def _find_decision(api: Api, title: str) -> dict | None:
    query = urllib.parse.quote(title)
    decisions = api.call("GET", f"/decisions?limit=500&q={query}")
    return next((decision for decision in decisions if decision["title"] == title), None)


def ensure_decisions(api: Api, summary: list[str]) -> None:
    for title, target in DECISION_TARGETS:
        existing = _find_decision(api, title)
        if existing is None:
            existing = api.call(
                "POST",
                "/decisions",
                json_body={"title": title, "brief": DECISION_BRIEF, "counterevidence": []},
                expected=(201,),
            )
            created = True
        else:
            created = False

        current = existing["status"]
        if current == target:
            state = "created" if created else "skipped"
            summary.append(f"decision ({target}): {state}")
            continue

        if current not in DECISION_PATH or target not in DECISION_PATH:
            raise SeedError(f"decision '{title}' is in unexpected state '{current}'")
        path = DECISION_PATH[DECISION_PATH.index(current) + 1 : DECISION_PATH.index(target) + 1]
        decision_id = existing["id"]
        for status in path:
            api.call(
                "POST",
                f"/decisions/{decision_id}/transition",
                json_body={"status": status, "reason": "Cold-start demo lifecycle"},
            )
        summary.append(f"decision ({target}): {'created' if created else 'advanced'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8100/v1")
    parser.add_argument("--tenant", default="tenant_alpha")
    parser.add_argument("--user", default="alpha.manager")
    parser.add_argument("--modeler", default=None, help="User used to propose the metric definition")
    args = parser.parse_args()

    api = Api(args.base_url, args.tenant, args.user)
    modeler = args.modeler or modeler_for(args.tenant)
    summary: list[str] = []
    try:
        dataset_id = ensure_dataset(api, modeler, summary)
        ensure_metric(api, modeler, dataset_id, summary)
        ensure_query(api, summary)
        ensure_monitoring_rule(api, dataset_id, summary)
        ensure_decisions(api, summary)
    except SeedError as err:
        print(f"seed failed: {err}", file=sys.stderr)
        return 1

    print("DecisionOS cold-start seed")
    for line in summary:
        print(f"  - {line}")
    print(f"created/advanced: {sum('created' in s or 'advanced' in s or 'repaired' in s for s in summary)}; "
          f"skipped: {sum('skipped' in s for s in summary)}; query: answered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
