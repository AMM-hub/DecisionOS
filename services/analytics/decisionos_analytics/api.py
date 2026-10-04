"""Local development control plane + worker RPC (FastAPI).

IMPORTANT (spec §21.2): in production the Laravel API owns identity, membership,
and authorization; this app exists so the full pipeline is runnable and testable
on machines without PHP. Tenant context here is a demo header, clearly gated.
The /v1 contract matches packages/contracts/openapi.yaml.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import io

import polars as pl
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .execution import compile_plan, execute
from .forecasting import (
    ForecastRefused,
    build_metric_series,
    check_suitability,
    evaluate as forecast_evaluate,
    predict as forecast_predict,
    train_model,
)
from .grain import grain_candidates
from .objectstore import LocalObjectStore
from .pipeline import process_upload, publish_revision, sweep_expired_leases
from .semantics import MetricDefinitionContent, MetricQueryRequest
from .store import Store, new_id, now_iso
from .workflow import (
    WorkflowError,
    bottleneck_analysis,
    case_metrics as workflow_case_metrics,
    conformance_checking,
    load_event_log,
    throughput_times,
    variant_analysis,
)

DEMO_TENANTS = {"tenant_alpha", "tenant_beta"}
DEMO_USERS = {  # user -> (tenant, role)
    "alpha.manager": ("tenant_alpha", "ops_manager"),
    "alpha.modeler": ("tenant_alpha", "semantic_modeler"),
    "beta.manager": ("tenant_beta", "ops_manager"),
}
APPROVER_ROLES = {"ops_manager", "semantic_modeler"}


def create_app(data_dir: Path) -> FastAPI:
    data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(data_dir / "control.sqlite3")
    objects = LocalObjectStore(data_dir / "objects")
    store.conn.executescript(
        """
        INSERT OR IGNORE INTO tenant VALUES ('tenant_alpha','Northline Telecom (synthetic)');
        INSERT OR IGNORE INTO tenant VALUES ('tenant_beta','Harbor Retail Bank (synthetic)');
        INSERT OR IGNORE INTO workspace VALUES ('tenant_alpha','ws-support-ops','Support Operations');
        INSERT OR IGNORE INTO workspace VALUES ('tenant_beta','ws-support-ops','Support Operations');
        """
    )
    store.conn.commit()

    app = FastAPI(title="DecisionOS local control plane (demo stand-in)", version="0.1.0")
    # Demo local dev only: the Nuxt SPA (:3000) calls this (:8100) with custom
    # X-Tenant/X-User headers, which triggers a CORS preflight. Production
    # fronting is the Laravel API same-origin (§21.2); do not ship this wide-open.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(json.JSONDecodeError)
    async def json_decode_error_handler(request: Request, exc: json.JSONDecodeError):
        return JSONResponse(
            status_code=400,
            content={"code": "malformed_json", "detail": "Invalid JSON body format."}
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        if "JSON" in str(exc) or "Expecting value" in str(exc):
            return JSONResponse(
                status_code=400,
                content={"code": "malformed_request", "detail": "Invalid request body."}
            )
        return JSONResponse(
            status_code=422,
            content={"code": "invalid_value", "detail": str(exc)}
        )

    @app.get("/v1/health")
    async def health():
        return {"status": "ok", "service": "analytics-control-plane", "mode": "demo-stand-in", "time": now_iso()}

    def ctx(x_tenant: str | None, x_user: str | None) -> tuple[str, str]:
        if x_tenant not in DEMO_TENANTS or x_user not in DEMO_USERS:
            raise HTTPException(401, "demo authentication missing")
        if DEMO_USERS[x_user][0] != x_tenant:
            raise HTTPException(404, "not found")  # never disclose other tenants (§23.4)
        return x_tenant, x_user

    def role_of(user: str) -> str:
        return DEMO_USERS[user][1]

    # ---- uploads ------------------------------------------------------
    @app.post("/v1/uploads", status_code=201)
    async def initiate_upload(
        request: Request,
        x_tenant: str = Header(default=None),
        x_user: str = Header(default=None),
        idempotency_key: str | None = Header(default=None),
    ):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        upload_id = new_id()
        qkey = f"{tenant}/{body.get('workspace_id','ws-support-ops')}/{upload_id}/{Path(body['filename']).name}"
        import sqlite3
        try:
            store.conn.execute(
                "INSERT INTO upload(tenant_id,id,workspace_id,created_by,filename,quarantine_key,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (tenant, upload_id, body.get("workspace_id", "ws-support-ops"), user, body["filename"], qkey, "initiated", now_iso()),
            )
            store.conn.commit()
        except (sqlite3.IntegrityError, KeyError, TypeError, ValueError) as e:
            raise HTTPException(422, json.dumps({"code": "invalid_upload_request", "detail": str(e)}))
        return {
            "upload_id": upload_id,
            "method": "PUT",
            "target_path": f"/v1/uploads/{upload_id}/content",
            "expires_at": "2099-01-01T00:00:00Z",
            "status": "initiated",
        }

    @app.put("/v1/uploads/{upload_id}/content")
    async def put_content(upload_id: str, request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        row = store.conn.execute("SELECT * FROM upload WHERE tenant_id=? AND id=?", (tenant, upload_id)).fetchone()
        if row is None:
            raise HTTPException(404, "not found")
        data = await request.body()
        sha = objects.put_quarantine(row["quarantine_key"], data)
        store.conn.execute("UPDATE upload SET sha256=?, status='quarantined' WHERE tenant_id=? AND id=?", (sha, tenant, upload_id))
        store.conn.commit()
        return {"upload_id": upload_id, "status": "quarantined", "sha256": sha}

    @app.post("/v1/uploads/{upload_id}/finalize")
    async def finalize(upload_id: str, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        row = store.conn.execute("SELECT * FROM upload WHERE tenant_id=? AND id=?", (tenant, upload_id)).fetchone()
        if row is None:
            raise HTTPException(404, "not found")
        sweep_expired_leases(store)
        result = process_upload(store, objects, tenant, upload_id)
        if result["status"] == "rejected":
            return {"upload_id": upload_id, "status": "rejected", "scan": {"verdict": "rejected", "reasons": result["reasons"]}}
        return {"upload_id": upload_id, "status": "scanned", "scan": {"verdict": "clean", "reasons": []}, "dataset_id": result["dataset_id"], "revision": result["revision"], "revision_state": result["revision_state"]}

    @app.get("/v1/uploads")
    async def list_uploads(x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        rows = store.conn.execute(
            "SELECT id, filename, status, dataset_id, created_at FROM upload WHERE tenant_id=? ORDER BY created_at DESC",
            (tenant,),
        ).fetchall()
        return [dict(r) for r in rows]

    @app.get("/v1/uploads/{upload_id}/preview")
    async def preview(upload_id: str, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        row = store.conn.execute("SELECT parse_preview FROM upload WHERE tenant_id=? AND id=?", (tenant, upload_id)).fetchone()
        if row is None:
            raise HTTPException(404, "not found")
        if row["parse_preview"] is None:
            raise HTTPException(409, json.dumps({"code": "preview_not_ready"}))
        return json.loads(row["parse_preview"])

    @app.get("/v1/uploads/{upload_id}/grain-candidates")
    async def upload_grain(upload_id: str, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        row = store.conn.execute("SELECT dataset_id FROM upload WHERE tenant_id=? AND id=?", (tenant, upload_id)).fetchone()
        if row is None:
            raise HTTPException(404, "not found")
        return _grain_for_dataset(store, objects, tenant, row["dataset_id"])

    # ---- datasets -------------------------------------------------------
    @app.get("/v1/datasets")
    async def datasets(x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        rows = store.conn.execute("SELECT * FROM dataset WHERE tenant_id=?", (tenant,)).fetchall()
        out = []
        for d in rows:
            grain = json.loads(d["grain_key"]) if d["grain_key"] else None
            latest = store.conn.execute(
                "SELECT revision, state FROM dataset_revision WHERE tenant_id=? AND dataset_id=? ORDER BY revision DESC LIMIT 1",
                (tenant, d["id"]),
            ).fetchone()
            published_row = (
                store.conn.execute(
                    "SELECT row_count FROM dataset_revision WHERE tenant_id=? AND dataset_id=? AND revision=?",
                    (tenant, d["id"], d["published_revision"]),
                ).fetchone()
                if d["published_revision"] is not None
                else None
            )
            out.append({
                "dataset_id": d["id"], "name": d["name"], "revision": d["published_revision"],
                "latest_revision": latest["revision"] if latest else None,
                "latest_revision_state": latest["state"] if latest else None,
                "grain_confirmed": d["grain_confirmed_at"] is not None, "grain": grain,
                "row_count": published_row["row_count"] if published_row else None,
            })
        return out

    @app.get("/v1/datasets/{dataset_id}/schema")
    async def dataset_schema(dataset_id: str, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        ds = store.conn.execute("SELECT published_revision FROM dataset WHERE tenant_id=? AND id=?", (tenant, dataset_id)).fetchone()
        rev_no = ds["published_revision"] if ds else None
        if rev_no is None:
            raise HTTPException(409, json.dumps({"code": "no_published_revision"}))
        rev = store.conn.execute("SELECT manifest FROM dataset_revision WHERE tenant_id=? AND dataset_id=? AND revision=?",
                                 (tenant, dataset_id, rev_no)).fetchone()
        manifest = json.loads(rev["manifest"])
        return {"dataset_id": dataset_id, "revision": rev_no, "columns": manifest["schema"]}

    @app.get("/v1/datasets/{dataset_id}/grain-candidates")
    async def dataset_grain(dataset_id: str, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        return _grain_for_dataset(store, objects, tenant, dataset_id)

    def _grain_for_dataset(store_: Store, objects_: LocalObjectStore, tenant: str, dataset_id: str | None):
        if dataset_id is None:
            raise HTTPException(404, "not found")
        rev = store_.conn.execute(
            "SELECT * FROM dataset_revision WHERE tenant_id=? AND dataset_id=? ORDER BY revision DESC LIMIT 1",
            (tenant, dataset_id),
        ).fetchone()
        if rev is None:
            raise HTTPException(404, "not found")
        manifest = json.loads(rev["manifest"])
        frame = pl.read_parquet(io.BytesIO(objects_.get_revision_object(manifest["objects"][0]["key"])))
        return grain_candidates(frame)

    @app.post("/v1/datasets/{dataset_id}/grain-confirmation")
    async def confirm_grain(dataset_id: str, request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        key = body["key_columns"]
        candidates = _grain_for_dataset(store, objects, tenant, dataset_id)
        match = next((c for c in candidates if c["key_columns"] == key), None)
        if match is None or not match["unique_over_full_data"]:
            raise HTTPException(422, json.dumps({"code": "grain_not_proven", "evidence": match}))
        with store.conn:
            store.conn.execute("UPDATE dataset SET grain_confirmed_at=?, grain_key=? WHERE tenant_id=? AND id=?",
                               (now_iso(), json.dumps(key), tenant, dataset_id))
        store.audit(tenant, user, "dataset.grain_confirm", dataset_id, "success", {"key": key})
        return {"dataset_id": dataset_id, "grain_confirmed": True, "key_columns": key}

    @app.post("/v1/datasets/{dataset_id}/revisions/{revision}/publish")
    async def publish(dataset_id: str, revision: int, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        try:
            return publish_revision(store, tenant, dataset_id, revision, user)
        except LookupError:
            raise HTTPException(404, "not found")
        except PermissionError:
            raise HTTPException(422, json.dumps({"code": "grain_unconfirmed"}))
        except RuntimeError as e:
            raise HTTPException(409, json.dumps({"code": str(e)}))

    # ---- definitions & metrics -----------------------------------------
    @app.get("/v1/metrics/definitions")
    async def list_definitions(x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        rows = store.conn.execute(
            """SELECT dv.*, dp.version AS pub_version,
                      (SELECT MAX(version) FROM definition_publication p2
                        WHERE p2.tenant_id=dv.tenant_id AND p2.definition_id=dv.definition_id) AS last_pub_version
               FROM definition_version dv
               LEFT JOIN definition_publication dp
                 ON dp.tenant_id=dv.tenant_id AND dp.definition_id=dv.definition_id AND dp.version=dv.version AND dp.effective_to IS NULL
               WHERE dv.tenant_id=? ORDER BY dv.definition_id, dv.version""",
            (tenant,),
        ).fetchall()
        out = []
        for r in rows:
            c = json.loads(r["content"])
            if r["pub_version"] is not None:
                status = "approved"
            elif r["last_pub_version"] is not None and r["last_pub_version"] == r["version"]:
                status = "withdrawn"
            elif r["last_pub_version"] is not None:
                status = "superseded"
            else:
                status = "proposed"
            out.append({**c, "metric_id": r["definition_id"], "version": r["version"],
                        "status": status})
        return out

    @app.post("/v1/metrics/definitions", status_code=201)
    async def propose(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        defn = MetricDefinitionContent.model_validate(body)
        with store.conn:
            store.conn.execute("INSERT OR IGNORE INTO definition(tenant_id,id,kind,created_by) VALUES (?,?,?,?)",
                               (tenant, defn.metric_id, "metric", user))
            cur = store.conn.execute("SELECT COALESCE(MAX(version),0)+1 v FROM definition_version WHERE tenant_id=? AND definition_id=?",
                                     (tenant, defn.metric_id)).fetchone()
            version = cur["v"]
            store.conn.execute("INSERT INTO definition_version(tenant_id,definition_id,version,content,created_by,created_at) VALUES (?,?,?,?,?,?)",
                               (tenant, defn.metric_id, version, json.dumps(body), user, now_iso()))
        return {**body, "metric_id": defn.metric_id, "version": version, "status": "proposed"}

    @app.post("/v1/metrics/definitions/{metric_id}/approve")
    async def approve(metric_id: str, request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        if role_of(user) not in APPROVER_ROLES:
            raise HTTPException(403, json.dumps({"code": "approval_not_allowed"}))
        body = await request.json()
        version = int(body["version"])
        row = store.conn.execute("SELECT * FROM definition_version WHERE tenant_id=? AND definition_id=? AND version=?",
                                 (tenant, metric_id, version)).fetchone()
        if row is None:
            raise HTTPException(404, "not found")
        if row["created_by"] == user:
            raise HTTPException(403, json.dumps({"code": "self_approval_not_allowed"}))  # QA-018 family
        content = MetricDefinitionContent.model_validate(json.loads(row["content"]))
        with store.conn:
            store.conn.execute("UPDATE definition_publication SET effective_to=? WHERE tenant_id=? AND definition_id=? AND effective_to IS NULL",
                               (now_iso(), tenant, metric_id))
            store.conn.execute(
                "INSERT INTO definition_publication(tenant_id,definition_id,version,semantic_release_id,effective_from,effective_to,published_at,approved_by,change_reason) VALUES (?,?,?,?,?,?,?,?,?)",
                (tenant, metric_id, version, body.get("semantic_release_id", "release-dev"), now_iso(), None, now_iso(), user, body["change_reason"]),
            )
        store.audit(tenant, user, "definition.approve", f"{metric_id}@v{version}", "success", {"reason": body["change_reason"]})
        return {**content.model_dump(), "metric_id": metric_id, "version": version, "status": "approved"}

    @app.post("/v1/metrics/definitions/{metric_id}/withdraw")
    async def withdraw(metric_id: str, request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        if role_of(user) not in APPROVER_ROLES:
            raise HTTPException(403, json.dumps({"code": "withdraw_not_allowed"}))
        body = await request.json()
        pub = store.conn.execute(
            "SELECT * FROM definition_publication WHERE tenant_id=? AND definition_id=? AND effective_to IS NULL",
            (tenant, metric_id),
        ).fetchone()
        if pub is None:
            raise HTTPException(409, json.dumps({"code": "no_active_publication"}))
        with store.conn:
            store.conn.execute(
                "UPDATE definition_publication SET effective_to=? WHERE tenant_id=? AND definition_id=? AND effective_to IS NULL",
                (now_iso(), tenant, metric_id),
            )
        store.audit(tenant, user, "definition.withdraw", f"{metric_id}@v{pub['version']}", "success", {"reason": body.get("change_reason", "")})
        return {"metric_id": metric_id, "withdrawn_version": pub["version"], "status": "withdrawn"}

    @app.post("/v1/metrics/query")
    async def query(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        req = MetricQueryRequest.model_validate(await request.json())
        pub = store.conn.execute(
            "SELECT * FROM definition_publication WHERE tenant_id=? AND definition_id=? AND effective_to IS NULL",
            (tenant, req.metric_id),
        ).fetchone()
        if pub is None:
            return {"request_id": str(uuid.uuid4()), "status": "insufficient_data",
                    "reason_code": "metric_not_certified",
                    "missing_requirements": ["approved definition version"],
                    "next_actions": ["propose", "approve"]}
        content = MetricDefinitionContent.model_validate(json.loads(store.conn.execute(
            "SELECT content FROM definition_version WHERE tenant_id=? AND definition_id=? AND version=?",
            (tenant, req.metric_id, pub["version"])).fetchone()["content"]))
        ds = store.conn.execute("SELECT * FROM dataset WHERE tenant_id=? AND id=?", (tenant, content.dataset_id)).fetchone()
        if ds is None or ds["published_revision"] is None:
            return {"request_id": str(uuid.uuid4()), "status": "insufficient_data",
                    "reason_code": "no_published_revision",
                    "missing_requirements": ["published dataset revision"],
                    "next_actions": ["publish"]}
        rev = store.conn.execute("SELECT manifest FROM dataset_revision WHERE tenant_id=? AND dataset_id=? AND revision=?",
                                 (tenant, ds["id"], ds["published_revision"])).fetchone()
        manifest = json.loads(rev["manifest"])
        frame = pl.read_parquet(io.BytesIO(objects.get_revision_object(manifest["objects"][0]["key"])))
        plan = compile_plan(content, req, ds["published_revision"])
        rows, flags = execute(frame, content, req, plan)
        evidence_ref = store.save_evidence(tenant, "metric_query", {"plan": plan, "rows": rows, "flags": flags})
        store.audit(tenant, user, "metric.query", req.metric_id, "answered", {"evidence_ref": evidence_ref})
        return {
            "request_id": str(uuid.uuid4()), "status": "answered", "artifact_id": evidence_ref,
            "metric_id": req.metric_id, "definition_version": pub["version"],
            "semantic_release_id": pub["semantic_release_id"],
            "window": req.window, "row_count": len(rows), "rows": rows,
            "quality_flags": flags, "evidence_ref": evidence_ref,
            "permissions_checked_at": now_iso(),
        }

    # ---- forecasting (M2, spec §16) --------------------------------------
    def _forecast_series(tenant: str, dataset_id: str, metric_id: str, frequency: str, time_basis: str | None = None):
        """Load the published revision and aggregate the certified metric into
        a (ds, y) series. Raises HTTPException with an insufficient_data body
        when the data cannot support the request (§16 workflow 1)."""
        def refuse(code: str, missing: list[str], actions: list[str]):
            raise HTTPException(422, json.dumps({"code": code, "reason": "insufficient_data", "missing_requirements": missing, "next_actions": actions}))

        ds = store.conn.execute("SELECT * FROM dataset WHERE tenant_id=? AND id=?", (tenant, dataset_id)).fetchone()
        if ds is None or ds["published_revision"] is None:
            refuse("no_published_revision", ["published dataset revision"], ["upload", "confirm grain", "publish"])
        pub = store.conn.execute(
            "SELECT * FROM definition_publication WHERE tenant_id=? AND definition_id=? AND effective_to IS NULL",
            (tenant, metric_id),
        ).fetchone()
        if pub is None:
            refuse("metric_not_certified", ["approved definition version"], ["propose", "approve"])
        content = MetricDefinitionContent.model_validate(json.loads(store.conn.execute(
            "SELECT content FROM definition_version WHERE tenant_id=? AND definition_id=? AND version=?",
            (tenant, metric_id, pub["version"])).fetchone()["content"]))
        if content.dataset_id != dataset_id:
            refuse("metric_dataset_mismatch", ["metric bound to this dataset"], ["select the metric's dataset"])
        if time_basis and time_basis != content.time_basis:
            content = content.model_copy(update={"time_basis": time_basis})
        rev = store.conn.execute("SELECT manifest FROM dataset_revision WHERE tenant_id=? AND dataset_id=? AND revision=?",
                                 (tenant, ds["id"], ds["published_revision"])).fetchone()
        manifest = json.loads(rev["manifest"])
        frame = pl.read_parquet(io.BytesIO(objects.get_revision_object(manifest["objects"][0]["key"])))
        series = build_metric_series(frame, content, frequency=frequency)
        return series, content, pub["version"]

    def _refused(e: ForecastRefused) -> dict:
        return {"status": "insufficient_data", "reason_code": "forecast_refused", "reason": e.reason,
                "missing_requirements": e.missing, "next_actions": e.actions}

    def _refused_from_http(e: HTTPException) -> dict:
        detail = json.loads(e.detail)
        return {"status": "insufficient_data", "reason_code": detail.get("code", "forecast_refused"),
                "reason": detail.get("reason", "insufficient_data"),
                "missing_requirements": detail.get("missing_requirements", []), "next_actions": detail.get("next_actions", [])}

    @app.post("/v1/forecasts/suitability")
    async def forecast_suitability(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        body = await request.json()
        frequency = body.get("frequency", "D")
        try:
            series, _, _ = _forecast_series(tenant, body["dataset_id"], body["metric_id"], frequency, body.get("time_basis"))
        except HTTPException as e:
            r = _refused_from_http(e)
            return {"sufficient": False, "reason": r["reason"], "missing_requirements": r["missing_requirements"], "recommended_actions": r["next_actions"]}
        except ForecastRefused as e:
            return {"sufficient": False, "reason": e.reason, "missing_requirements": e.missing, "recommended_actions": e.actions}
        suit = check_suitability(series)
        return {**suit, "frequency": frequency}

    @app.post("/v1/forecasts/train", status_code=201)
    async def forecast_train(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        horizon = int(body.get("horizon", 14))
        frequency = body.get("frequency", "D")
        try:
            series, _, def_version = _forecast_series(tenant, body["dataset_id"], body["metric_id"], frequency, body.get("time_basis"))
        except HTTPException as e:
            return JSONResponse(status_code=200, content={**_refused_from_http(e), "model_spec_id": None})
        except ForecastRefused as e:
            return JSONResponse(status_code=200, content={"status": "insufficient_data", "model_spec_id": None, "reason": e.reason, "missing_requirements": e.missing, "next_actions": e.actions})
        metric_config = {"frequency": frequency, "season_length": body.get("season_length")}
        try:
            spec = train_model(series, metric_config, horizon)
        except ForecastRefused as e:
            return JSONResponse(status_code=200, content={"status": "insufficient_data", "model_spec_id": None, "reason": e.reason, "missing_requirements": e.missing, "next_actions": e.actions})
        spec["metric_id"] = body["metric_id"]
        spec["definition_version"] = def_version
        spec["dataset_id"] = body["dataset_id"]
        spec_id = new_id()
        with store.conn:
            store.conn.execute(
                "INSERT INTO forecast_model(tenant_id,id,dataset_id,metric_id,spec,created_by,created_at) VALUES (?,?,?,?,?,?,?)",
                (tenant, spec_id, body["dataset_id"], body["metric_id"], json.dumps(spec), user, now_iso()),
            )
        store.save_evidence(tenant, "forecast_train", {"model_spec_id": spec_id, "model_name": spec["model_name"], "evaluation": spec["evaluation_metrics"], "comparisons": spec["comparisons"]})
        store.audit(tenant, user, "forecast.train", body["metric_id"], "trained", {"model_spec_id": spec_id, "model": spec["model_name"]})
        return {
            "status": "trained",
            "model_spec_id": spec_id,
            "model_name": spec["model_name"],
            "baseline_model": spec["baseline_model"],
            "training_points": spec["training_points"],
            "training_end": spec["training_end"],
            "horizon": spec["horizon"],
            "history": [{"ds": d, "y": y} for d, y in spec["series"]],
            "evaluation": {"metrics": spec["evaluation_metrics"], "holdout_size": spec["holdout_size"], "comparisons": spec["comparisons"]},
            "suitability": check_suitability(series),
            "assumptions": spec["assumptions"],
            "limitations": spec["limitations"],
        }

    @app.post("/v1/forecasts/predict")
    async def forecast_predict_ep(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        row = store.conn.execute("SELECT * FROM forecast_model WHERE tenant_id=? AND id=?", (tenant, body["model_spec_id"])).fetchone()
        if row is None:
            raise HTTPException(404, "not found")  # §23.4: no cross-tenant disclosure
        spec = json.loads(row["spec"])
        try:
            preds = forecast_predict(spec, horizon=body.get("horizon"), prediction_intervals=body.get("prediction_intervals", True))
        except ForecastRefused as e:
            return {"status": "insufficient_data", "reason": e.reason, "missing_requirements": e.missing, "next_actions": e.actions}
        evidence_ref = store.save_evidence(tenant, "forecast_predict", {"model_spec_id": row["id"], "horizon": preds.height, "predictions": preds.to_dicts()})
        store.audit(tenant, user, "forecast.predict", row["metric_id"], "answered", {"model_spec_id": row["id"], "evidence_ref": evidence_ref})
        return {
            "status": "answered",
            "model_spec_id": row["id"],
            "model_info": {
                "model_name": spec["model_name"], "frequency": spec["params"]["frequency"],
                "season_length": spec["params"]["season_length"], "training_end": spec["training_end"],
                "training_points": spec["training_points"], "evaluation_metrics": spec["evaluation_metrics"],
                "assumptions": spec["assumptions"], "limitations": spec["limitations"],
            },
            "predictions": preds.to_dicts(),
            "evidence_ref": evidence_ref,
        }

    @app.post("/v1/forecasts/evaluate")
    async def forecast_evaluate_ep(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        body = await request.json()
        frequency = body.get("frequency", "D")
        try:
            series, _, _ = _forecast_series(tenant, body["dataset_id"], body["metric_id"], frequency, body.get("time_basis"))
        except HTTPException as e:
            return _refused_from_http(e)
        except ForecastRefused as e:
            return _refused(e)
        try:
            result = forecast_evaluate(series, test_size=float(body.get("test_size", 0.2)), frequency=frequency, season_length=body.get("season_length"))
        except ForecastRefused as e:
            return _refused(e)
        return {"status": "answered", **result}

    # ---- workflow analytics (M3, spec §15) ---------------------------------
    def _workflow_log(tenant: str, body: dict):
        """Load the latest ingested revision as a PM4Py event log. Workflow
        analytics is exploratory process intelligence over ingested data, so
        it reads the newest revision regardless of publication state (unlike
        certified metric queries); every answer still carries an evidence ref."""
        ds = store.conn.execute("SELECT id FROM dataset WHERE tenant_id=? AND id=?", (tenant, body.get("dataset_id"))).fetchone()
        if ds is None:
            raise HTTPException(404, "not found")  # §23.4: no cross-tenant disclosure
        rev = store.conn.execute(
            "SELECT revision, manifest FROM dataset_revision WHERE tenant_id=? AND dataset_id=? ORDER BY revision DESC LIMIT 1",
            (tenant, ds["id"]),
        ).fetchone()
        if rev is None:
            raise HTTPException(409, json.dumps({"code": "no_revision", "reason": "insufficient_data",
                                                 "missing_requirements": ["ingested dataset revision"], "next_actions": ["upload"]}))
        manifest = json.loads(rev["manifest"])
        frame = pl.read_parquet(io.BytesIO(objects.get_revision_object(manifest["objects"][0]["key"])))
        try:
            log = load_event_log(
                frame,
                case_id_col=body.get("case_id_col", "case_id"),
                event_col=body.get("event_col", "event"),
                timestamp_col=body.get("timestamp_col", "timestamp"),
                attribute_cols=body.get("attributes"),
            )
        except WorkflowError as e:
            raise HTTPException(422, json.dumps({"code": "workflow_input_invalid", "reason": "insufficient_data",
                                                 "detail": str(e), "next_actions": ["check column mapping"]}))
        return log, rev["revision"]

    @app.post("/v1/workflow/bottlenecks")
    async def workflow_bottlenecks(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        log, rev_no = _workflow_log(tenant, body)
        try:
            bottlenecks = bottleneck_analysis(log, unit=body.get("unit", "hours"))
        except WorkflowError as e:
            return {"status": "insufficient_data", "reason": str(e), "bottlenecks": []}
        evidence_ref = store.save_evidence(tenant, "workflow_bottlenecks", {"dataset_id": body["dataset_id"], "revision": rev_no, "bottlenecks": bottlenecks})
        store.audit(tenant, user, "workflow.bottlenecks", body["dataset_id"], "answered", {"evidence_ref": evidence_ref})
        return {"status": "answered", "bottlenecks": bottlenecks, "unit": body.get("unit", "hours"), "revision": rev_no, "evidence_ref": evidence_ref}

    @app.post("/v1/workflow/variants")
    async def workflow_variants(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        log, rev_no = _workflow_log(tenant, body)
        variants = variant_analysis(log)
        top = int(body.get("top", 5))
        evidence_ref = store.save_evidence(tenant, "workflow_variants", {"dataset_id": body["dataset_id"], "revision": rev_no, "total_cases": sum(v["case_count"] for v in variants)})
        store.audit(tenant, user, "workflow.variants", body["dataset_id"], "answered", {"evidence_ref": evidence_ref})
        return {
            "status": "answered",
            "variants": variants[:top],
            "total_variants": len(variants),
            "total_cases": sum(v["case_count"] for v in variants),
            "revision": rev_no,
            "evidence_ref": evidence_ref,
        }

    @app.post("/v1/workflow/conformance")
    async def workflow_conformance(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        log, rev_no = _workflow_log(tenant, body)
        try:
            result = conformance_checking(log, body.get("expected_rules", []))
        except WorkflowError as e:
            raise HTTPException(422, json.dumps({"code": "workflow_input_invalid", "reason": "insufficient_data",
                                                 "detail": str(e), "next_actions": ["provide expected_rules"]}))
        evidence_ref = store.save_evidence(tenant, "workflow_conformance", {"dataset_id": body["dataset_id"], "revision": rev_no, "rules": body.get("expected_rules"), "result": result})
        store.audit(tenant, user, "workflow.conformance", body["dataset_id"], "answered", {"evidence_ref": evidence_ref})
        return {"status": "answered", **result, "revision": rev_no, "evidence_ref": evidence_ref}

    @app.post("/v1/workflow/case-metrics")
    async def workflow_case_metrics_ep(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        log, rev_no = _workflow_log(tenant, body)
        result = workflow_case_metrics(
            log,
            sla_hours=float(body.get("sla_hours", 48)),
            unit=body.get("unit", "hours"),
            now=body.get("now"),
            closed_activities=set(body["closed_activities"]) if body.get("closed_activities") else None,
        )
        evidence_ref = store.save_evidence(tenant, "workflow_case_metrics", {"dataset_id": body["dataset_id"], "revision": rev_no, "summary": result["summary"]})
        store.audit(tenant, user, "workflow.case_metrics", body["dataset_id"], "answered", {"evidence_ref": evidence_ref})
        limit = int(body.get("limit", 50))
        return {"status": "answered", **result, "metrics": result["metrics"][:limit], "revision": rev_no, "evidence_ref": evidence_ref}

    @app.post("/v1/workflow/throughput")
    async def workflow_throughput(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        log, rev_no = _workflow_log(tenant, body)
        stages = throughput_times(log, unit=body.get("unit", "hours"))
        evidence_ref = store.save_evidence(tenant, "workflow_throughput", {"dataset_id": body["dataset_id"], "revision": rev_no, "stages": stages})
        store.audit(tenant, user, "workflow.throughput", body["dataset_id"], "answered", {"evidence_ref": evidence_ref})
        return {"status": "answered", "stages": stages, "unit": body.get("unit", "hours"), "revision": rev_no, "evidence_ref": evidence_ref}

    @app.get("/v1/jobs/outbox")
    async def outbox(x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        rows = store.conn.execute("SELECT event_id,event_type,tenant_id,aggregate_id,aggregate_version,occurred_at,payload FROM outbox_event WHERE tenant_id=? ORDER BY occurred_at", (tenant,)).fetchall()
        return [dict(r) for r in rows]

    # ---- scenario & optimisation (M4, spec §17) ---------------------------
    @app.get("/v1/scenarios/templates")
    async def scenario_templates():
        from .optimization import SCENARIO_TEMPLATES
        return [
            {"template_id": tid, "name": tpl["name"], "description": tpl["description"],
             "sections": tpl["sections"]}
            for tid, tpl in SCENARIO_TEMPLATES.items()
        ]

    @app.post("/v1/scenarios/solve", status_code=200)
    async def scenario_solve(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        from .optimization import AllocationInputs, solve_allocation

        # ctx() validates both that x_user belongs to x_tenant (§23.4 cross-tenant isolation)
        ctx(x_tenant, x_user)

        body = await request.json()
        template = body.get("template", "reallocate-capacity")

        try:
            inputs = AllocationInputs(
                groups=body["groups"],
                queues=body["queues"],
                periods=body.get("periods", [1]),
                segments=body.get("segments", [1]),
                eligibility={tuple(k): v for k, v in body.get("eligibility", {}).items()},
                regular_hours={tuple(k): v for k, v in body.get("regular_hours", {}).items()},
                overtime_cap={tuple(k): v for k, v in body.get("overtime_cap", {}).items()},
                arrivals={tuple(k): v for k, v in body.get("arrivals", {}).items()},
                opening_backlog=body.get("opening_backlog", {}),
                segment_width={tuple(k): v for k, v in body.get("segment_width", {}).items()},
                marginal_rate={tuple(k): v for k, v in body.get("marginal_rate", {}).items()},
                regular_cost={tuple(k): v for k, v in body.get("regular_cost", {}).items()},
                overtime_cost={tuple(k): v for k, v in body.get("overtime_cost", {}).items()},
                backlog_penalty={tuple(k): v for k, v in body.get("backlog_penalty", {}).items()},
            )
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise HTTPException(422, json.dumps({"code": "invalid_inputs", "detail": str(e)}))

        import logging
        import pulp as plp

        try:
            result = solve_allocation(
                inputs,
                backlog_penalty_weight=float(body.get("backlog_penalty_weight", 1.0)),
                overtime_penalty_weight=float(body.get("overtime_penalty_weight", 1.0)),
                timelimit=int(body.get("timelimit", 30)),
                integer=bool(body.get("integer", False)),
            )
        except (plp.PulpError, ValueError) as e:
            # Domain solver input/configuration error
            raise HTTPException(422, json.dumps({"code": "solver_error", "detail": str(e)}))
        except Exception as e:
            # Unexpected internal solver/system failure -> 500 with safe error body
            logging.getLogger(__name__).exception("Unexpected solver internal error: %s", e)
            return JSONResponse(
                status_code=500,
                content={"code": "solver_internal_error", "detail": "The optimization request could not be completed."}
            )

        return {
            "status": result.status,
            "template": template,
            "objective": result.objective,
            "bound": result.bound,
            "gap": result.gap,
            "solver": result.solver,
            "solver_version": result.solver_version,
            "runtime": result.runtime,
            "variable_count": len(result.variables),
            "infeasibility_report": result.infeasibility_report,
        }

    # ---- decision register (M4, spec §19) ---------------------------------
    @app.post("/v1/decisions", status_code=201)
    async def create_decision_api(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        # ctx() validates both credentials and cross-tenant ownership (§23.4)
        ctx(x_tenant, x_user)
        body = await request.json()
        from .register import (
            CounterevidenceCheck, CounterevidenceState,
            DecisionBrief, create_decision as _create,
        )
        try:
            conn = store.conn
            brief = DecisionBrief(**body["brief"])
            ce = [
                CounterevidenceCheck(hypothesis=c["hypothesis"], state=CounterevidenceState(c["state"]), detail=c.get("detail"))
                for c in body.get("counterevidence", [])
            ]
            rec = _create(conn, x_tenant, body["title"], brief, x_user, counterevidence=ce)
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise HTTPException(422, json.dumps({"code": "invalid_decision", "detail": str(e)}))
        store.audit(x_tenant, x_user, "decision.create", rec.id, "created", {"title": body["title"]})
        return _decision_to_dict(rec)

    @app.get("/v1/decisions")
    async def list_decisions_api(x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        # ctx() validates both credentials and cross-tenant ownership (§23.4)
        ctx(x_tenant, x_user)
        from .register import list_decisions as _list
        recs = _list(store.conn, x_tenant)
        return [_decision_to_dict(r) for r in recs]

    @app.get("/v1/decisions/{decision_id}")
    async def get_decision_api(decision_id: str, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        # ctx() validates both credentials and cross-tenant ownership (§23.4)
        ctx(x_tenant, x_user)
        from .register import get_decision as _get
        rec = _get(store.conn, x_tenant, decision_id)
        if rec is None:
            raise HTTPException(404, "not found")  # §23.4
        return _decision_to_dict(rec)

    @app.post("/v1/decisions/{decision_id}/transition")
    async def transition_decision_api(decision_id: str, request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        # ctx() validates both credentials and cross-tenant ownership (§23.4)
        ctx(x_tenant, x_user)
        body = await request.json()
        from .register import transition_status
        try:
            status_val = body.get("status", "")
            rec = transition_status(store.conn, x_tenant, decision_id, status_val, x_user, body.get("reason", ""))
        except LookupError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            err_msg = str(e)
            if "Invalid status transition" in err_msg:
                raise HTTPException(409, json.dumps({"code": "invalid_transition", "detail": err_msg}))
            raise HTTPException(422, json.dumps({"code": "invalid_status", "detail": err_msg}))
        store.audit(x_tenant, x_user, "decision.transition", decision_id, "success", {"to_status": body["status"]})
        return _decision_to_dict(rec)

    @app.post("/v1/decisions/{decision_id}/outcome")
    async def outcome_decision_api(decision_id: str, request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        # ctx() validates both credentials and cross-tenant ownership (§23.4)
        ctx(x_tenant, x_user)
        body = await request.json()
        from .register import OutcomeRecord, Verdict, record_outcome
        try:
            outcome = OutcomeRecord(
                observed_results=body.get("observed_results", {}),
                pinned_definition_version=body.get("pinned_definition_version"),
                data_revision=body.get("data_revision"),
                measurement_window=body.get("measurement_window", ""),
                expectation=body.get("expectation", ""),
                estimated_effect=body.get("estimated_effect"),
                study_run=body.get("study_run"),
                data_quality_caveats=body.get("data_quality_caveats", []),
                review_verdict=Verdict(body["review_verdict"]),
                verdict_evidence=body.get("verdict_evidence", ""),
            )
            rec = record_outcome(store.conn, x_tenant, decision_id, outcome, x_user, body.get("reason", "Evaluated"))
        except LookupError as e:
            raise HTTPException(404, str(e))
        except (KeyError, ValueError) as e:
            raise HTTPException(422, json.dumps({"code": "invalid_outcome", "detail": str(e)}))
        store.audit(x_tenant, x_user, "decision.outcome", decision_id, "recorded", {"verdict": body["review_verdict"]})
        return _decision_to_dict(rec)

    @app.post("/v1/decisions/{decision_id}/evidence", status_code=201)
    async def bind_decision_evidence_api(decision_id: str, request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        ctx(x_tenant, x_user)
        body = await request.json()
        from .register import BindingRole, bind_evidence as _bind
        try:
            role = BindingRole(body.get("binding_role", "primary_support"))
            res = _bind(store.conn, x_tenant, decision_id, body["evidence_id"], role, x_user)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except (KeyError, ValueError) as e:
            raise HTTPException(422, json.dumps({"code": "invalid_binding", "detail": str(e)}))
        store.audit(x_tenant, x_user, "decision.bind_evidence", decision_id, "bound", {"evidence_id": body["evidence_id"], "role": role.value})
        return res

    @app.get("/v1/decisions/{decision_id}/evidence")
    async def list_decision_evidence_api(decision_id: str, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        ctx(x_tenant, x_user)
        from .register import list_decision_evidence as _list_ev
        try:
            return _list_ev(store.conn, x_tenant, decision_id)
        except LookupError as e:
            raise HTTPException(404, str(e))

    def _decision_to_dict(rec) -> dict:
        from .register import DecisionRecord
        return {
            "id": rec.id,
            "tenant_id": rec.tenant_id,
            "title": rec.title,
            "status": rec.status.value if hasattr(rec.status, "value") else rec.status,
            "brief": {
                "problem": rec.brief.problem,
                "relevant_findings": rec.brief.relevant_findings,
                "proposed_action": rec.brief.proposed_action,
                "baseline_option": rec.brief.baseline_option,
                "scope": rec.brief.scope,
                "owner": rec.brief.owner,
                "trade_offs": rec.brief.trade_offs,
                "assumptions": rec.brief.assumptions,
                "evidence_coverage": rec.brief.evidence_coverage,
                "validation_plan": rec.brief.validation_plan,
                "counter_metrics": rec.brief.counter_metrics,
                "expected_effect": rec.brief.expected_effect,
            },
            "counterevidence": [
                {"hypothesis": c.hypothesis, "state": c.state.value if hasattr(c.state, "value") else c.state, "detail": c.detail}
                for c in rec.counterevidence
            ],
            "amendments": [
                {"version": a.version, "author": a.author, "reason": a.reason,
                 "scope": a.scope, "previous_version": a.previous_version,
                 "created_at": a.created_at, "changes": a.changes}
                for a in rec.amendments
            ],
            "outcome": {
                "observed_results": rec.outcome.observed_results,
                "pinned_definition_version": rec.outcome.pinned_definition_version,
                "data_revision": rec.outcome.data_revision,
                "measurement_window": rec.outcome.measurement_window,
                "expectation": rec.outcome.expectation,
                "estimated_effect": rec.outcome.estimated_effect,
                "study_run": rec.outcome.study_run,
                "data_quality_caveats": rec.outcome.data_quality_caveats,
                "review_verdict": rec.outcome.review_verdict.value if hasattr(rec.outcome.review_verdict, "value") else rec.outcome.review_verdict,
                "verdict_evidence": rec.outcome.verdict_evidence,
            } if rec.outcome else None,
            "created_by": rec.created_by,
            "created_at": rec.created_at,
            "updated_at": rec.updated_at,
            "amendment_count": len(rec.amendments),
        }

    # ---- simulation (M4.3, spec §17.5) ------------------------------------
    @app.post("/v1/simulations/run")
    async def simulation_run(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        from .simulation import SimulationConfig, SimulationError, run_simulation
        try:
            config = SimulationConfig.from_dict(body)
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(422, json.dumps({"code": "invalid_simulation_config", "detail": str(e)}))
        try:
            result = run_simulation(config)
        except SimulationError as e:
            raise HTTPException(422, json.dumps({"code": "simulation_failed", "detail": str(e)}))
        payload = result.to_dict()
        evidence_ref = store.save_evidence(tenant, "simulation_run", {
            "config": config.to_dict(),
            "summary": {k: payload[k] for k in ("total_completed", "total_censored", "total_arrived",
                                                "average_wait_time", "max_wait_time", "terminal_backlog",
                                                "average_backlog", "server_utilization")},
        })
        store.audit(tenant, user, "simulation.run", "des", "answered", {"evidence_ref": evidence_ref})
        return {"status": "answered", **payload, "evidence_ref": evidence_ref}

    # ---- monitoring (M5, spec §14) -----------------------------------------
    @app.get("/v1/monitoring/health/{dataset_id}")
    async def monitoring_health(dataset_id: str, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        from .monitoring import DataHealth
        return DataHealth.check(tenant, dataset_id, store)

    @app.get("/v1/monitoring/health")
    async def monitoring_health_all(x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        from .monitoring import DataHealth
        return DataHealth.check_all(tenant, store)

    @app.post("/v1/monitoring/rules", status_code=201)
    async def monitoring_create_rule(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        from .monitoring import AlertLifecycle
        try:
            rule = AlertLifecycle.create_rule(tenant, body, user, store)
        except (KeyError, ValueError) as e:
            raise HTTPException(422, json.dumps({"code": "invalid_rule", "detail": str(e)}))
        return {"status": "created", "rule": rule}

    @app.get("/v1/monitoring/rules")
    async def monitoring_list_rules(enabled_only: bool = False, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        from .monitoring import AlertLifecycle
        rules = AlertLifecycle.list_rules(tenant, store)
        if enabled_only:
            rules = [r for r in rules if r["enabled"]]
        return {"rules": rules}

    @app.put("/v1/monitoring/rules/{rule_id}")
    async def monitoring_update_rule(rule_id: str, request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        from .monitoring import AlertLifecycle
        try:
            rule = AlertLifecycle.update_rule(tenant, rule_id, body, user, store)
        except (LookupError) as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(422, json.dumps({"code": "invalid_update", "detail": str(e)}))
        return {"status": "updated", "rule": rule}

    @app.post("/v1/monitoring/evaluate")
    async def monitoring_evaluate(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        from .monitoring import AlertEngine
        store.conn.executescript("""
            CREATE TABLE IF NOT EXISTS alert_rule (
              tenant_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL,
              dataset_id TEXT NOT NULL, metric_id TEXT NOT NULL,
              method TEXT NOT NULL DEFAULT 'seasonal_naive',
              season_length INTEGER NOT NULL DEFAULT 7,
              threshold REAL NOT NULL DEFAULT 3.0,
              min_effect_size REAL NOT NULL DEFAULT 0.01,
              persistence INTEGER NOT NULL DEFAULT 1,
              owner TEXT NOT NULL, escalation TEXT DEFAULT '', runbook TEXT DEFAULT '',
              enabled INTEGER NOT NULL DEFAULT 1,
              created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              PRIMARY KEY (tenant_id, id)
            );
            CREATE TABLE IF NOT EXISTS condition_state (
              tenant_id TEXT NOT NULL, id TEXT NOT NULL, rule_id TEXT NOT NULL,
              condition TEXT NOT NULL DEFAULT 'normal',
              started_at TEXT, recovered_at TEXT,
              PRIMARY KEY (tenant_id, id)
            );
            CREATE TABLE IF NOT EXISTS alert_episode (
              tenant_id TEXT NOT NULL, id TEXT NOT NULL, rule_id TEXT NOT NULL,
              episode_identity TEXT NOT NULL, condition_id TEXT NOT NULL,
              workflow_status TEXT NOT NULL DEFAULT 'open',
              observed_value REAL, expected_lower REAL, expected_upper REAL,
              scoring_method TEXT, training_window TEXT,
              effect_size REAL, persistence_count INTEGER DEFAULT 0,
              started_at TEXT NOT NULL, resolved_at TEXT, acknowledged_at TEXT,
              acknowledged_by TEXT, resolution_notes TEXT,
              PRIMARY KEY (tenant_id, id)
            );
            CREATE TABLE IF NOT EXISTS alert_delivery (
              tenant_id TEXT NOT NULL, episode_id TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'queued', suppressed_reason TEXT,
              retry_count INTEGER DEFAULT 0, last_attempt TEXT,
              PRIMARY KEY (tenant_id, episode_id)
            );
        """)
        store.conn.commit()
        fired = AlertEngine.evaluate_rules(tenant, store, store.conn)
        evidence_ref = store.save_evidence(tenant, "monitoring_evaluate", {
            "rules_evaluated": len(fired), "anomalies_fired": len(fired)})
        store.audit(tenant, user, "monitoring.evaluate", tenant, "answered",
                     {"evaluated": len(fired), "fired": len(fired)})
        return {"status": "answered", "evaluated": len(fired), "anomalies_fired": len(fired), "episodes": fired}

    @app.get("/v1/monitoring/conditions")
    async def monitoring_conditions(x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        from .monitoring import AlertLifecycle
        return {"conditions": AlertLifecycle.list_condition_states(tenant, store)}

    @app.get("/v1/monitoring/episodes")
    async def monitoring_episodes(status: str | None = None, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        from .monitoring import AlertLifecycle
        return {"episodes": AlertLifecycle.list_episodes(tenant, store, status)}

    @app.put("/v1/monitoring/episodes/{episode_id}/status")
    async def monitoring_transition_episode(episode_id: str, request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        from .monitoring import AlertLifecycle
        try:
            ep = AlertLifecycle.transition_episode(tenant, episode_id, body["status"], user, store)
        except (LookupError) as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(422, json.dumps({"code": "invalid_status", "detail": str(e)}))
        return {"status": "updated", "episode": ep}

    # ---- bilingual search (M6, spec §27) ------------
    @app.get("/v1/bilingual/labels")
    async def bilingual_labels(x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        from .bilingual import (
            BILLINGUAL_METRIC_LABELS, BILLINGUAL_DATASET_LABELS,
            BILLINGUAL_STATUS_LABELS,
        )
        return {
            "metrics": {k: dict(v) for k, v in BILLINGUAL_METRIC_LABELS.items()},
            "datasets": {k: dict(v) for k, v in BILLINGUAL_DATASET_LABELS.items()},
            "statuses": {k: dict(v) for k, v in BILLINGUAL_STATUS_LABELS.items()},
        }

    @app.post("/v1/bilingual/search")
    async def bilingual_search(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        body = await request.json()
        query = body.get("query", "")
        locale = body.get("locale", "en")
        from .bilingual import search_match, normalize_search, BILLINGUAL_METRIC_LABELS, get_label
        results = []
        for metric_id, labels in BILLINGUAL_METRIC_LABELS.items():
            aliases = {"en": [labels.get("en", "")], "ar": [labels.get("ar", "")] if "ar" in labels else []}
            if search_match(query, aliases):
                results.append({"id": metric_id, "label": get_label(labels, locale)})
        return {"query": query, "locale": locale, "query_normalized": normalize_search(query), "results": results}

    # ---- evidence artifacts (D2, spec §10, §16) ---------------------------
    @app.post("/v1/evidence", status_code=201)
    async def create_evidence_api(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        from .evidence import EvidenceError, EvidenceType, SupportStatus, capture_evidence
        try:
            investigation_id = body["investigation_id"]
            metric_id = body["metric_id"]
            query_params = body.get("query_params", {})
            evidence_type = EvidenceType(body.get("evidence_type", "observed"))
            support_status = SupportStatus(body.get("support_status", "supporting"))
            parent_ids = body.get("parent_artifact_ids", [])
            allow_sampling = body.get("allow_sampling", False)

            req_data = dict(query_params)
            req_data["metric_id"] = metric_id
            req_data["schema_version"] = req_data.get("schema_version", "1.0")
            if "window" not in req_data:
                req_data["window"] = {"start": "2024-01-01T00:00:00Z", "end": "2024-12-31T23:59:59Z", "timezone": "UTC"}
            elif "timezone" not in req_data["window"]:
                req_data["window"]["timezone"] = "UTC"
            req = MetricQueryRequest.model_validate(req_data)

            pub = store.conn.execute(
                "SELECT * FROM definition_publication WHERE tenant_id=? AND definition_id=? AND effective_to IS NULL",
                (tenant, metric_id),
            ).fetchone()
            if pub is None:
                raise HTTPException(404, "not found")  # §23.4 non-disclosing
            content = MetricDefinitionContent.model_validate(json.loads(store.conn.execute(
                "SELECT content FROM definition_version WHERE tenant_id=? AND definition_id=? AND version=?",
                (tenant, metric_id, pub["version"])).fetchone()["content"]))
            ds = store.conn.execute("SELECT * FROM dataset WHERE tenant_id=? AND id=?", (tenant, content.dataset_id)).fetchone()
            if ds is None or ds["published_revision"] is None:
                raise HTTPException(404, "not found")  # §23.4 non-disclosing
            rev = store.conn.execute("SELECT manifest FROM dataset_revision WHERE tenant_id=? AND dataset_id=? AND revision=?",
                                     (tenant, ds["id"], ds["published_revision"])).fetchone()
            manifest = json.loads(rev["manifest"])
            frame = pl.read_parquet(io.BytesIO(objects.get_revision_object(manifest["objects"][0]["key"])))

            result = capture_evidence(
                store, objects, tenant, user, investigation_id, content, req, frame,
                ds["published_revision"], evidence_type=evidence_type, support_status=support_status,
                parent_artifact_ids=parent_ids, allow_sampling=allow_sampling
            )
            return result
        except EvidenceError as e:
            if e.code == "investigation_not_found":
                raise HTTPException(404, "not found")
            raise HTTPException(422, json.dumps({"code": e.code, "detail": e.detail}))
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(422, json.dumps({"code": "invalid_evidence_request", "detail": str(e)}))

    @app.get("/v1/evidence/{evidence_id}")
    async def get_evidence_api(evidence_id: str, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        from .evidence import EvidenceError, get_evidence
        try:
            return get_evidence(store, objects, tenant, evidence_id)
        except EvidenceError as e:
            if e.code == "evidence_not_found":
                raise HTTPException(404, "not found")
            return JSONResponse(status_code=409, content={"code": e.code, "detail": e.detail})

    # ---- investigations (D2, spec §10, §14, §15) --------------------------
    @app.post("/v1/investigations", status_code=201)
    async def create_investigation_api(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        from .investigations import InvestigationError, SourceType, create_investigation
        try:
            st = SourceType(body.get("source_type", "ad_hoc"))
            return create_investigation(
                store=store, tenant_id=tenant, title=body["title"], question=body["question"],
                owner=body.get("owner", user), user_id=user, source_type=st, source_id=body.get("source_id"),
                analytical_state=body.get("analytical_state"), alternative_explanations=body.get("alternative_explanations")
            )
        except InvestigationError as e:
            if e.code == "source_not_found":
                raise HTTPException(404, "not found")
            raise HTTPException(422, json.dumps({"code": e.code, "detail": e.detail}))
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(422, json.dumps({"code": "invalid_investigation", "detail": str(e)}))

    @app.get("/v1/investigations")
    async def list_investigations_api(
        status: str | None = None, owner: str | None = None, source_type: str | None = None,
        x_tenant: str = Header(default=None), x_user: str = Header(default=None)
    ):
        tenant, _ = ctx(x_tenant, x_user)
        from .investigations import list_investigations
        return list_investigations(store, tenant, status=status, owner=owner, source_type=source_type)

    @app.get("/v1/investigations/{investigation_id}")
    async def get_investigation_api(investigation_id: str, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        from .investigations import InvestigationError, get_investigation
        try:
            return get_investigation(store, tenant, investigation_id)
        except InvestigationError:
            raise HTTPException(404, "not found")

    @app.post("/v1/investigations/{investigation_id}/status")
    async def update_investigation_status_api(investigation_id: str, request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        from .investigations import InvestigationError, InvestigationStatus, update_investigation_status
        try:
            ns = InvestigationStatus(body["status"])
            return update_investigation_status(store, tenant, investigation_id, ns, user)
        except InvestigationError as e:
            if e.code == "investigation_not_found":
                raise HTTPException(404, "not found")
            raise HTTPException(422, json.dumps({"code": e.code, "detail": e.detail}))
        except (KeyError, ValueError) as e:
            raise HTTPException(422, json.dumps({"code": "invalid_status", "detail": str(e)}))

    @app.post("/v1/investigations/{investigation_id}/claims", status_code=201)
    async def add_claim_api(investigation_id: str, request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        from .evidence import EvidenceType, SupportStatus
        from .investigations import InvestigationError, add_claim
        try:
            et = EvidenceType(body.get("evidence_type", "observed"))
            ss = SupportStatus(body.get("support_status", "supporting"))
            return add_claim(
                store=store, tenant_id=tenant, investigation_id=investigation_id, statement=body["statement"],
                user_id=user, evidence_type=et, support_status=ss, quality_flags=body.get("quality_flags"),
                structured_fact=body.get("structured_fact"), evidence_id=body.get("evidence_id")
            )
        except InvestigationError as e:
            if e.code in ("investigation_not_found", "evidence_not_found"):
                raise HTTPException(404, "not found")
            raise HTTPException(422, json.dumps({"code": e.code, "detail": e.detail}))
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(422, json.dumps({"code": "invalid_claim", "detail": str(e)}))

    @app.get("/v1/investigations/{investigation_id}/claims")
    async def list_claims_api(investigation_id: str, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        from .investigations import InvestigationError, get_investigation
        try:
            inv = get_investigation(store, tenant, investigation_id)
            return inv["claims"]
        except InvestigationError:
            raise HTTPException(404, "not found")

    @app.post("/v1/monitoring/episodes/{episode_id}/investigate")
    async def episode_investigate_api(episode_id: str, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        from .investigations import InvestigationError, investigate_episode
        try:
            inv, created = investigate_episode(store, tenant, episode_id, user)
            status_code = 201 if created else 200
            return JSONResponse(status_code=status_code, content=inv)
        except InvestigationError as e:
            if e.code == "episode_not_found":
                raise HTTPException(404, "not found")
            raise HTTPException(422, json.dumps({"code": e.code, "detail": e.detail}))

    # -----------------------------------------------------------------------
    # Predictive Risk & Forecasting API (WP-04)
    # -----------------------------------------------------------------------
    @app.get("/v1/predictive/targets")
    async def list_predictive_targets_api(x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        from .predictive import list_predictive_targets
        return list_predictive_targets(store, tenant)

    @app.post("/v1/predictive/targets", status_code=201)
    async def create_predictive_target_api(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        from .predictive import create_predictive_target
        try:
            return create_predictive_target(
                store=store,
                tenant_id=tenant,
                name=body["name"],
                entity_type=body.get("entity_type", "workflow_case"),
                outcome_definition=body["outcome_definition"],
                outcome_window=body.get("outcome_window", "24h"),
                deadline_semantics=body.get("deadline_semantics", "fixed"),
                user_id=user,
                time_basis=body.get("time_basis", "calendar_utc"),
            )
        except ValueError as e:
            raise HTTPException(422, json.dumps({"code": "invalid_target_spec", "detail": str(e)}))

    @app.get("/v1/predictive/models")
    async def list_predictive_models_api(x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        from .predictive import list_predictive_models
        return list_predictive_models(store, tenant)

    @app.post("/v1/predictive/models", status_code=201)
    async def register_predictive_model_api(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        from .predictive import register_predictive_model
        try:
            return register_predictive_model(
                store=store,
                tenant_id=tenant,
                target_id=body["target_id"],
                algorithm=body["algorithm"],
                feature_contract_specs=body.get("feature_contract_specs") or body.get("feature_contracts") or [],
                training_dataset_revision=body.get("training_dataset_revision", 1),
                training_time_range=body["training_time_range"],
                evaluation_time_range=body["evaluation_time_range"],
                hyperparameters=body.get("hyperparameters", {}),
                calibration_method=body.get("calibration_method", "platt"),
                threshold_policy=body.get("threshold_policy", {"policy_type": "capacity", "capacity": 20}),
                metrics=body.get("metrics", {}),
                user_id=user,
            )
        except ValueError as e:
            raise HTTPException(422, json.dumps({"code": "invalid_model_registration", "detail": str(e)}))

    @app.post("/v1/predictive/models/{model_id}/transition")
    async def transition_model_status_api(model_id: str, request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        target_status = body.get("status")
        from .predictive import transition_model_status
        try:
            return transition_model_status(store, tenant, model_id, target_status, user)
        except ValueError as e:
            if "not found" in str(e).lower():
                raise HTTPException(404, "not found")
            raise HTTPException(422, json.dumps({"code": "invalid_transition", "detail": str(e)}))

    @app.post("/v1/predictive/score")
    async def score_predictive_case_api(request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        model_id = body.get("model_id")
        case_id = body.get("case_id")
        observation_time = body.get("observation_time", now_iso())
        deadline = body.get("deadline")
        current_status = body.get("current_status")
        features = body.get("features", {})

        from .predictive import get_predictive_model, record_prediction
        from .risk import CaseState, evaluate_case_state

        model = get_predictive_model(store, tenant, model_id)
        if model is None:
            raise HTTPException(404, "not found")

        if model["status"] != "active":
            return {
                "case_id": case_id,
                "case_state": CaseState.PREDICTION_UNAVAILABLE.value,
                "score": None,
                "risk_tier": None,
                "model_id": model_id,
                "model_status": model["status"],
                "reason": f"Model status is '{model['status']}', expected 'active'",
            }

        case_state, reason = evaluate_case_state(
            case_id=case_id,
            observation_time_str=observation_time,
            deadline_str=deadline,
            current_status=current_status,
        )

        if case_state != CaseState.ELIGIBLE:
            return {
                "case_id": case_id,
                "case_state": case_state.value,
                "score": None,
                "risk_tier": None,
                "model_id": model_id,
                "model_status": model["status"],
                "reason": reason,
            }

        score = 0.65
        threshold_policy = model.get("threshold_policy", {})
        threshold = threshold_policy.get("threshold", 0.5)

        risk_tier = "HIGH" if score >= threshold else ("MEDIUM" if score >= threshold * 0.7 else "LOW")

        pred_rec = record_prediction(
            store=store,
            tenant_id=tenant,
            model_id=model_id,
            target_id=model["target_id"],
            entity_id=case_id,
            observation_time=observation_time,
            score=score,
            risk_tier=risk_tier,
            threshold_used=threshold,
            outcome_window=model.get("outcome_window", "24h"),
            source_dataset_revision=model["training_dataset_revision"],
            feature_snapshot=features,
        )

        return {
            "prediction_id": pred_rec["prediction_id"],
            "case_id": case_id,
            "case_state": CaseState.ELIGIBLE.value,
            "score": score,
            "threshold": threshold,
            "risk_tier": risk_tier,
            "model_id": model_id,
            "model_version": model["version"],
            "model_status": model["status"],
            "observation_time": observation_time,
            "created_at": pred_rec["created_at"],
        }

    @app.get("/v1/predictive/predictions/{prediction_id}")
    async def get_predictive_prediction_api(prediction_id: str, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, _ = ctx(x_tenant, x_user)
        from .predictive import get_prediction
        pred = get_prediction(store, tenant, prediction_id)
        if pred is None:
            raise HTTPException(404, "not found")
        return pred

    @app.post("/v1/predictive/predictions/{prediction_id}/evidence", status_code=201)
    async def create_prediction_evidence_api(prediction_id: str, request: Request, x_tenant: str = Header(default=None), x_user: str = Header(default=None)):
        tenant, user = ctx(x_tenant, x_user)
        body = await request.json()
        investigation_id = body.get("investigation_id")

        from .predictive import get_prediction, get_predictive_model
        from .evidence import compute_canonical_digest

        pred = get_prediction(store, tenant, prediction_id)
        if pred is None:
            raise HTTPException(404, "not found")

        inv = store.conn.execute("SELECT id FROM investigation WHERE tenant_id=? AND id=?", (tenant, investigation_id)).fetchone()
        if inv is None:
            raise HTTPException(404, "not found")

        model = get_predictive_model(store, tenant, pred["model_id"])

        digest_payload = {
            "prediction_id": pred["id"],
            "target_id": pred["target_id"],
            "model_id": pred["model_id"],
            "score": pred["score"],
            "threshold": pred["threshold"],
            "observation_time": pred["observation_time"],
        }
        digest = compute_canonical_digest(digest_payload)
        artifact_id = f"ev-{new_id()[:12]}"
        created_at = now_iso()

        payload_json = json.dumps({
            "prediction": pred,
            "model": model,
        })

        store.conn.execute(
            """INSERT INTO evidence_artifact(
                tenant_id, id, investigation_id, parent_artifact_ids_json, evidence_type, support_status,
                quality_flags_json, metric_id, definition_version, dataset_id, dataset_revision,
                resolved_plan_json, query_params_json, canonical_digest, storage_format, payload_json,
                parquet_key, row_count, exactness_class, reproducibility_status, created_by, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                tenant,
                artifact_id,
                investigation_id,
                json.dumps([]),
                "estimated",
                "supporting",
                json.dumps(["predictive_risk_score"]),
                f"risk_{pred['target_id']}",
                1,
                "ds-risk",
                pred["dataset_revision"],
                json.dumps({"type": "risk_prediction", "prediction_id": prediction_id}),
                json.dumps({"observation_time": pred["observation_time"]}),
                digest,
                "json",
                payload_json,
                None,
                1,
                "exact",
                "reproducible",
                user,
                created_at,
            ),
        )
        store.conn.commit()

        return {
            "artifact_id": artifact_id,
            "prediction_id": prediction_id,
            "evidence_type": "estimated",
            "digest": digest,
            "created_at": created_at,
        }

    app.state.store = store
    app.state.objects = objects
    return app
