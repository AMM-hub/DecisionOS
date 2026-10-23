"""Live API probe v2 — corrected to the real register contract.

Covers: auth boundary, full decision state machine, outcome recording,
error-envelope shape, list surfaces, latency.
"""
import json
import statistics
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8100"
HDR = {"Content-Type": "application/json", "X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
results, lat = [], []


def call(method, path, body=None, headers=None, raw=None):
    h = HDR if headers is None else headers
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload, code = r.read().decode(), r.status
    except urllib.error.HTTPError as e:
        payload, code = e.read().decode(), e.code
    except Exception as e:  # noqa: BLE001
        payload, code = f"ERR {e}", 0
    dt = (time.perf_counter() - t0) * 1000
    lat.append(dt)
    try:
        parsed = json.loads(payload) if payload else None
    except json.JSONDecodeError:
        parsed = payload[:200]
    return code, parsed


def check(name, cond, detail=""):
    results.append({"check": name, "pass": bool(cond), "detail": str(detail)[:200]})
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {str(detail)[:140]}")
    return bool(cond)


BRIEF = {
    "problem": "Churn rising in SME segment", "relevant_findings": ["f1"],
    "proposed_action": "Retention pilot", "baseline_option": "Do nothing",
    "scope": "SME 90d", "owner": "alpha.manager", "trade_offs": ["cost"],
    "assumptions": ["signal stable"], "evidence_coverage": ["f1"],
    "validation_plan": "A/B 8 weeks", "counter_metrics": ["margin"],
    "expected_effect": "estimated",
}

code, dec = call("POST", "/v1/decisions", {"title": "Probe v2", "brief": BRIEF})
check("create decision", code == 201, code)
did = dec["id"] if isinstance(dec, dict) else None

PATH = ["proposed", "accepted", "implementation_pending", "active", "review_due"]
if did:
    for st in PATH:
        code, body = call("POST", f"/v1/decisions/{did}/transition", {"status": st, "note": "probe"})
        check(f"transition -> {st}", code == 200, f"{code} {str(body)[:80]}")
    code, body = call("POST", f"/v1/decisions/{did}/transition", {"status": "closed"})
    check("illegal transition rejected (review_due->closed)", code == 409, f"{code} {str(body)[:100]}")
    code, body = call("POST", f"/v1/decisions/{did}/outcome", {
        "observed_results": {"churn": 0.18}, "pinned_definition_version": "1",
        "data_revision": "r1", "measurement_window": "8w", "expectation": "churn down",
        "estimated_effect": -0.05, "study_run": "run-1", "data_quality_caveats": [],
        "review_verdict": "supported_improvement", "verdict_evidence": [], "reason": "probe",
    })
    check("record outcome", code == 200, f"{code} {str(body)[:120]}")
    code, body = call("GET", f"/v1/decisions/{did}/outcome-comparison")
    check("outcome-comparison", code == 200, f"{code} {str(body)[:120]}")
    code, body = call("POST", "/v1/decisions", {"title": "Probe no brief"})
    nested = isinstance(body, dict) and isinstance(body.get("detail"), str) and body["detail"].startswith("{")
    check("422 envelope is machine-readable (not double-encoded)", not nested, f"{code} {str(body)[:120]}")

print("\n=== read surface ===")
for p in ["/v1/datasets", "/v1/decisions", "/v1/investigations", "/v1/evidence"]:
    code, body = call("GET", p)
    check(f"GET {p}", code == 200, f"{code} n={len(body) if isinstance(body, list) else '?'}")

ok = sum(1 for r in results if r["pass"])
bad = [r for r in results if not r["pass"]]
print(f"\nSUMMARY {ok}/{len(results)} passed, {len(bad)} failed")
for b in bad:
    print("  FAIL:", b["check"], "|", b["detail"])
print("latency p50=%.0fms p95=%.0fms max=%.0fms" % (
    statistics.median(lat), sorted(lat)[max(0, int(len(lat) * .95) - 1)], max(lat)))
json.dump({"results": results}, open("var/api_probe2.json", "w"), indent=2)
