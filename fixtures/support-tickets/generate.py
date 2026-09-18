#!/usr/bin/env python3
"""Generate the DecisionOS synthetic support-ticket fixtures (two tenants).

All data is synthetic. No values come from any real customer.
Golden expectations are computed independently here with plain Python and
stored in manifest.json; the analytics pipeline must reproduce them (spec §29.1).

Run:  python fixtures/support-tickets/generate.py
"""

from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "data"
SEED = 20260915
rng = random.Random(SEED)

TENANTS = {
    "tenant_alpha": {
        "org": "Northline Telecom (synthetic)",
        "n_cases": 420,
        "branches": ["MAN-01", "MAN-02", "RIF-01", "SHB-01"],
        "channels": ["email", "web", "phone", "mobile_app"],
        "priorities": ["low", "normal", "high", "urgent"],
        "queue_weights": [0.42, 0.28, 0.2, 0.1],
        # first-response rate target per branch (probability a case gets a response)
        "response_p": {"MAN-01": 0.93, "MAN-02": 0.9, "RIF-01": 0.74, "SHB-01": 0.86},
        "median_resp_hours": {"MAN-01": 4.0, "MAN-02": 6.0, "RIF-01": 14.0, "SHB-01": 8.0},
    },
    "tenant_beta": {
        "org": "Harbor Retail Bank (synthetic)",
        "n_cases": 130,
        "branches": ["CCU-01", "CCU-02"],
        "channels": ["email", "secure_message", "phone"],
        "priorities": ["normal", "high"],
        "queue_weights": [0.6, 0.4],
        "response_p": {"CCU-01": 0.88, "CCU-02": 0.82},
        "median_resp_hours": {"CCU-01": 5.0, "CCU-02": 9.0},
    },
}

SUBJECTS_EN = [
    "Billing dispute on monthly invoice",
    "Internet outage in area",
    "SIM card replacement request",
    "Plan upgrade inquiry",
    "Roaming charges question",
    "Router configuration help",
]
SUBJECTS_AR = [
    "مشكلة في فاتورة الاشتراك الشهري",
    "انقطاع خدمة الإنترنت في المنطقه",
    "طلب تغيير باقة البيانات",
    "استفسار عن رسوم التجوال الدولي",
]

WINDOW_START = datetime(2026, 1, 1, tzinfo=timezone.utc)  # Asia/Bahrain = UTC+3, no DST
WINDOW_END = datetime(2026, 4, 1, tzinfo=timezone.utc)


def gen_case_id(prefix: str, n: int) -> str:
    # Leading zeros MUST survive parsing (QA-001)
    return f"{prefix}{n:05d}"


def gen_tenant(tenant: str, cfg: dict) -> dict:
    cases_dir = OUT / tenant
    cases_dir.mkdir(parents=True, exist_ok=True)

    cases, events = [], []
    golden = {
        "org": cfg["org"],
        "window": {"start": WINDOW_START.isoformat().replace("+00:00", "Z"),
                    "end": WINDOW_END.isoformat().replace("+00:00", "Z"),
                    "timezone": "UTC"},
        "rows_total": cfg["n_cases"],
        "per_branch": {b: {"eligible": 0, "responded": 0, "resp_hours": []} for b in cfg["branches"]},
        "overall": {"eligible": 0, "responded": 0},
    }

    for i in range(1, cfg["n_cases"] + 1):
        branch = rng.choices(cfg["branches"], weights=cfg["queue_weights"])[0]
        created = WINDOW_START + timedelta(
            days=rng.uniform(0, (WINDOW_END - WINDOW_START).total_seconds() / 86400)
        )
        created = created.replace(microsecond=0)
        status = rng.choices(
            ["resolved", "closed", "open", "cancelled", "spam"],
            weights=[0.5, 0.2, 0.2, 0.07, 0.03],
        )[0]
        eligible = status not in ("spam",)  # eligibility: exclude spam; cancelled stays eligible
        responded = eligible and rng.random() < cfg["response_p"][branch]
        resp_hours = None
        if responded:
            med = cfg["median_resp_hours"][branch]
            resp_hours = round(max(0.1, rng.lognormvariate(__import__("math").log(med), 0.55)), 4)
        resolved_at = created + timedelta(hours=resp_hours + rng.uniform(1, 48)) if status in ("resolved", "closed") and resp_hours else None

        case = {
            "case_id": gen_case_id("T", i),
            "subject": rng.choice(SUBJECTS_AR) if rng.random() < 0.25 else rng.choice(SUBJECTS_EN),
            "priority": rng.choice(cfg["priorities"]),
            "channel": rng.choice(cfg["channels"]),
            "originating_branch": branch,
            "status": status,
            "created_at": created.isoformat().replace("+00:00", "Z"),
            "first_response_at": (created + timedelta(hours=resp_hours)).isoformat().replace("+00:00", "Z") if resp_hours else "",
            "resolved_at": resolved_at.isoformat().replace("+00:00", "Z") if resolved_at else "",
            "reopen_count": rng.choice([0, 0, 0, 1, 2]),
            "document_wait_seconds": rng.randrange(0, 90000) if rng.random() < 0.3 else 0,
            "customer_id": gen_case_id("C", rng.randrange(1, cfg["n_cases"])),
        }
        cases.append(case)

        if eligible:
            golden["per_branch"][branch]["eligible"] += 1
            golden["overall"]["eligible"] += 1
            if resp_hours:
                golden["per_branch"][branch]["responded"] += 1
                golden["overall"]["responded"] += 1
                golden["per_branch"][branch]["resp_hours"].append(resp_hours)

        n_events = rng.choice([2, 3, 4, 5])
        for e in range(n_events):
            events.append({
                "event_id": f"E{tenant[-5:]}{i:05d}{e:02d}",
                "case_id": case["case_id"],  # repeated case_id in history is EXPECTED, not a defect (§33.1)
                "event_type": ["created", "assigned", "customer_reply", "agent_note", "status_change"][min(e, 4)],
                "occurred_at": case["created_at"] if e == 0 else (created + timedelta(hours=rng.uniform(0, 60))).isoformat().replace("+00:00", "Z"),
                "agent_id": gen_case_id("AG", rng.randrange(1, 25)),
                "note": "",
            })

    with open(cases_dir / "tickets_cases.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(cases[0].keys()))
        w.writeheader(); w.writerows(cases)
    with open(cases_dir / "ticket_events.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(events[0].keys()))
        w.writeheader(); w.writerows(events)
    with open(cases_dir / "agents.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["agent_id", "branch", "role", "active"])
        for a in range(1, 26):
            w.writerow([gen_case_id("AG", a), rng.choice(cfg["branches"]), rng.choice(["agent", "senior_agent", "supervisor"]), rng.choice([True, True, False])])

    # median goldens
    for b, d in golden["per_branch"].items():
        hs = sorted(d.pop("resp_hours"))
        d["median_first_response_hours"] = None if not hs else (hs[len(hs)//2] if len(hs) % 2 else round((hs[len(hs)//2-1]+hs[len(hs)//2])/2, 4))
    return golden


def gen_dirty_fixture() -> None:
    """Adversarial fixture exercising parse safety + grain refusal (QA-001/002/004/005)."""
    d = OUT / "adversarial"
    d.mkdir(parents=True, exist_ok=True)
    rows = [
        ["case_id", "subject", "priority", "channel", "originating_branch", "status", "created_at", "first_response_at", "resolved_at", "reopen_count", "document_wait_seconds", "customer_id"],
        ["00123", "Leading zero id must survive", "normal", "email", "MAN-01", "open", "2026-02-01T10:00:00Z", "", "", "0", "0", "0000456"],
        ["T00012", "Ambiguous date", "normal", "email", "MAN-01", "open", "03/04/2026", "", "", "0", "0", "C00012"],
        ["T00012", "Duplicate case_id -> grain violation", "high", "web", "RIF-01", "open", "2026-02-02T10:00:00Z", "", "", "0", "0", "C00013"],
        ["", "Null candidate key component", "low", "web", "MAN-02", "open", "2026-02-03T10:00:00Z", "", "", "0", "0", "C00014"],
        ["T00015", "Formula injection", "low", "email", "MAN-01", "open", "2026-02-04T10:00:00Z", "", "", "0", "0", "=1+1"],
        ["T00016", "Row with wrong column count is rejected", "low", "email", "MAN-01", "open"],
        ["999999999999999999999", "Long numeric-looking id preserved as text", "low", "phone", "SHB-01", "open", "2026-02-05T10:00:00Z", "", "", "0", "0", "C00016"],
    ]
    with open(d / "tickets_cases_dirty.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def main() -> None:
    manifest = {"generated_with_seed": SEED, "note": "Synthetic data only. Golden values computed independently of the analytics pipeline.", "tenants": {}}
    for t, cfg in TENANTS.items():
        manifest["tenants"][t] = gen_tenant(t, cfg)
    gen_dirty_fixture()
    manifest["tenants"]["tenant_alpha"]["per_branch"]["RIF-01"]["note"] = "intentionally lower response rate for branch-comparison demo (§33.2)"
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
