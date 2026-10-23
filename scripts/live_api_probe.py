"""Black-box live API probe for DecisionOS control plane (port 8100).

Exercises the real HTTP surface as a client would, and records status codes,
latency, and payload/contract shape. Run with:

    env -u PYTHONPATH .venv/Scripts/python.exe ../../scripts/live_api_probe.py
"""
import json
import statistics
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8100"
HEAD = {"Content-Type": "application/json", "X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
results = []
lat = []


def call(method, path, body=None, headers=None, raw_body=None):
    h = dict(HEAD)
    if headers is not None:
        h = headers
    data = raw_body if raw_body is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            payload = r.read().decode("utf-8", "replace")
            code = r.status
    except urllib.error.HTTPError as e:
        payload = e.read().decode("utf-8", "replace")
        code = e.code
    except Exception as e:  # noqa: BLE001
        payload, code = f"CONNECTION_ERROR: {e}", 0
    dt = (time.perf_counter() - t0) * 1000
    lat.append(dt)
    try:
        parsed = json.loads(payload) if payload else None
    except json.JSONDecodeError:
        parsed = payload[:200]
    results.append({"step": path, "method": method, "status": code, "ms": round(dt, 1)})
    return code, parsed, payload


def check(name, cond, detail=""):
    results.append({"check": name, "pass": bool(cond), "detail": detail})
    print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")
    return bool(cond)


BRIEF = {
    "problem": "Churn rising in SME segment",
    "relevant_findings": ["f1", "f2"],
    "proposed_action": "Launch retention pilot",
    "baseline_option": "Do nothing",
    "scope": "SME accounts, 90 days",
    "owner": "alpha.manager",
    "trade_offs": ["cost"],
    "assumptions": ["churn signal stable"],
    "evidence_coverage": ["f1"],
    "validation_plan": "A/B 8 weeks",
    "counter_metrics": ["margin"],
    "expected_effect": "estimated",
}

print("=== 1. Health & auth boundary ===")
code, body, _ = call("GET", "/v1/health", headers={"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"})
check("health 200", code == 200, body)
code, _, _ = call("GET", "/v1/datasets", headers={})
check("no-auth datasets 401", code == 401, f"got {code}")
code, _, _ = call("GET", "/v1/datasets", headers={"X-Tenant": "test-tenant", "X-User": "qa-operator"})
check("synthetic tenant 401", code == 401, f"got {code}")

print("\n=== 2. Decision lifecycle ===")
code, dec, _ = call("POST", "/v1/decisions", {"title": "Probe decision", "brief": BRIEF})
check("create decision 201", code == 201, f"got {code} {str(dec)[:120]}")
did = dec.get("id") if isinstance(dec, dict) else None
if did:
    code, got, _ = call("GET", f"/v1/decisions/{did}")
    check("fetch decision 200", code == 200 and got.get("id") == did, f"got {code}")
    code, lst, _ = call("GET", "/v1/decisions")
    check("list decisions contains new", isinstance(lst, list) and any(d.get("id") == did for d in lst), f"n={len(lst) if isinstance(lst,list) else '?'}")
    for st in ("review", "approved", "implemented"):
        code, tr, _ = call("POST", f"/v1/decisions/{did}/transition", {"status": st, "note": f"probe {st}"})
        check(f"transition -> {st}", code in (200, 201), f"got {code} {str(tr)[:120]}")
    code, bad, raw = call("POST", f"/v1/decisions/{did}/transition", {"status": "not_a_status"})
    check("invalid transition rejected", code >= 400, f"got {code}")
    code, oc, _ = call("POST", f"/v1/decisions/{did}/outcome", {"outcome": "success", "detail": "probe"})
    check("record outcome", code in (200, 201), f"got {code} {str(oc)[:100]}")
    code, ev, _ = call("POST", f"/v1/decisions/{did}/evidence", {"kind": "metric", "ref": "probe-ref"})
    check("attach evidence", code in (200, 201), f"got {code} {str(ev)[:100]}")

print("\n=== 3. Error contract consistency (spec §23) ===")
code, mal, _ = call("POST", "/v1/decisions", raw_body=b"{bad json")
flat = isinstance(mal, dict) and "code" in mal and "detail" in mal
check("malformed JSON -> flat {code,detail}", code == 400 and flat, f"got {code} {str(mal)[:120]}")
code, inv, _ = call("POST", "/v1/decisions", {"title": "x"})
nested = isinstance(inv, dict) and isinstance(inv.get("detail"), str) and inv["detail"].strip().startswith("{")
check("validation error envelope NOT double-encoded", not nested, f"got {code} {str(inv)[:160]}")
code, nf, _ = call("GET", "/v1/decisions/does-not-exist")
check("missing decision 404", code == 404, f"got {code}")
code, _, _ = call("POST", "/v1/evidence", {"kind": "x"})
check("bad evidence payload 4xx", 400 <= code < 500, f"got {code}")

print("\n=== 4. Read-surface breadth ===")
for path in ["/v1/datasets", "/v1/investigations", "/v1/pilots", "/v1/metrics/definitions",
             "/v1/monitoring/rules", "/v1/monitoring/episodes", "/v1/predictive/models",
             "/v1/predictive/targets", "/v1/scenarios/templates", "/v1/monitoring/conditions",
             "/v1/pilots/semantic-pack", "/v1/jobs/outbox"]:
    code, body, _ = call("GET", path)
    ok = code == 200
    n = len(body) if isinstance(body, list) else (len(body) if isinstance(body, dict) else "?")
    check(f"GET {path}", ok, f"{code} size={n}")

print("\n=== 5. Pilot summary ===")
code, pilots, _ = call("GET", "/v1/pilots")
pid = pilots[0]["id"] if isinstance(pilots, list) and pilots and isinstance(pilots[0], dict) else None
if pid:
    code, summ, _ = call("GET", f"/v1/pilots/{pid}/summary")
    check("pilot summary 200", code == 200, f"got {code}")
    if isinstance(summ, dict):
        print("   summary keys:", list(summ.keys())[:12])
else:
    print("   no pilot present; skipping summary")

print("\n=== 6. Pagination / list bounding ===")
code, lst, _ = call("GET", "/v1/decisions")
has_params = False
spec = json.loads(urllib.request.urlopen(BASE + "/openapi.json", timeout=10).read())
for p, ops in spec["paths"].items():
    for m, op in ops.items():
        params = [x["name"] for x in op.get("parameters", [])]
        if any(k in params for k in ("limit", "offset", "page", "cursor")):
            check(f"pagination on {m.upper()} {p}", True, str(params))
            has_params = True
if not has_params:
    check("list endpoints expose pagination", False, "no limit/offset/cursor params anywhere in OpenAPI")

ok = sum(1 for r in results if r.get("pass") is True)
bad = [r for r in results if r.get("pass") is False]
print(f"\n=== SUMMARY: {ok} passed, {len(bad)} failed ===")
for b in bad:
    print("  FAILED:", b["check"], "|", b["detail"])
print("latency ms: p50=%.0f p95=%.0f max=%.0f n=%d" % (
    statistics.median(lat), sorted(lat)[int(len(lat) * 0.95) - 1], max(lat), len(lat)))
json.dump({"results": results, "latency": [round(x, 1) for x in lat]},
          open("var/api_probe_results.json", "w"), indent=2)
print("wrote var/api_probe_results.json")
