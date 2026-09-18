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
        store.conn.execute(
            "INSERT INTO upload(tenant_id,id,workspace_id,created_by,filename,quarantine_key,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (tenant, upload_id, body.get("workspace_id", "ws-support-ops"), user, body["filename"], qkey, "initiated", now_iso()),
        )
        store.conn.commit()
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

        if x_tenant not in DEMO_TENANTS or x_user not in DEMO_USERS:
            raise HTTPException(401, "demo authentication missing")

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

        try:
            result = solve_allocation(
                inputs,
                backlog_penalty_weight=float(body.get("backlog_penalty_weight", 1.0)),
                overtime_penalty_weight=float(body.get("overtime_penalty_weight", 1.0)),
                timelimit=int(body.get("timelimit", 30)),
                integer=bool(body.get("integer", False)),
            )
        except Exception as e:
            return JSONResponse(status_code=200, content={
                "status": "failed", "reason": str(e),
                "template": template,
            })

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

    app.state.store = store
    app.state.objects = objects
    return app
