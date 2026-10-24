"""Read-only tool registry for DecisionOS Intelligence.

Tools are the only source of numbers in an AI answer. Each handler delegates to
an existing deterministic engine (analytics query, metric execution, decision
register, monitoring, pilot, predictive registry) and returns a uniform
``{ok, data, evidence_ref?, error?}`` envelope. The agent never computes values
itself; it only selects tools and narrates their results.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from ..analytics.query import AnalyticsQuery, AnalyticsQueryError, run_query
from ..execution import compile_plan, execute
from ..monitoring import AlertLifecycle
from ..objectstore import LocalObjectStore
from ..pilot import pilot_summary
from ..predictive import get_predictive_model
from ..register import get_decision, list_decisions
from ..risk import evaluate_case_state
from ..security import has_permission
from ..semantics import MetricDefinitionContent, MetricQueryRequest
from ..store import Store, now_iso
from .constants import MODEL_ROLES  # noqa: F401 - re-exported role vocabulary for callers

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    store: Store
    objects: LocalObjectStore
    tenant_id: str
    user: str
    role: str = "ops_manager"
    limiter: Any = None

    def rate_limited(self) -> bool:
        if self.limiter is None:
            return False
        allowed, _retry = self.limiter.allow(f"ai-tool:{self.tenant_id}:{self.user}")
        return not allowed


def _ok(data: Any, evidence_ref: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True, "data": data}
    if evidence_ref:
        result["evidence_ref"] = evidence_ref
    return result


def _fail(code: str, error: str, *, refused: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "code": code, "error": error}
    if refused:
        result["refused"] = True
    return result


def _decision_dict(record) -> dict[str, Any]:
    return {
        "id": record.id,
        "title": record.title,
        "status": record.status.value if hasattr(record.status, "value") else record.status,
        "created_by": record.created_by,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "brief": {
            "problem": record.brief.problem,
            "proposed_action": record.brief.proposed_action,
            "baseline_option": record.brief.baseline_option,
            "owner": record.brief.owner,
            "expected_effect": record.brief.expected_effect,
        },
        "counterevidence": [
            {"hypothesis": c.hypothesis, "state": c.state.value if hasattr(c.state, "value") else c.state}
            for c in record.counterevidence
        ],
        "outcome_recorded": record.outcome is not None,
    }


# ---- tool handlers --------------------------------------------------------


def _list_datasets(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or 20), 100))
    rows = ctx.store.conn.execute(
        "SELECT id, name, published_revision FROM dataset WHERE tenant_id=? ORDER BY created_at DESC LIMIT ?",
        (ctx.tenant_id, limit),
    ).fetchall()
    datasets = []
    for row in rows:
        revision = row["published_revision"]
        row_count = None
        state = None
        if revision is not None:
            rev = ctx.store.conn.execute(
                "SELECT row_count, state FROM dataset_revision WHERE tenant_id=? AND dataset_id=? AND revision=?",
                (ctx.tenant_id, row["id"], revision),
            ).fetchone()
            if rev is not None:
                row_count = rev["row_count"]
                state = rev["state"]
        datasets.append(
            {
                "dataset_id": row["id"],
                "name": row["name"],
                "published_revision": revision,
                "published_revision_state": state,
                "row_count": row_count,
            }
        )
    return _ok({"datasets": datasets, "count": len(datasets)})


def _dataset_schema(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    dataset_id = args.get("dataset_id")
    if not dataset_id:
        return _fail("missing_field", "dataset_id is required")
    dataset = ctx.store.conn.execute(
        "SELECT id, name, published_revision FROM dataset WHERE tenant_id=? AND id=?",
        (ctx.tenant_id, dataset_id),
    ).fetchone()
    if dataset is None:
        return _fail("not_found", "dataset not found")
    revision = dataset["published_revision"]
    if revision is None:
        return _fail("no_published_revision", "No published revision exists for this dataset.")
    rev = ctx.store.conn.execute(
        "SELECT manifest FROM dataset_revision WHERE tenant_id=? AND dataset_id=? AND revision=?",
        (ctx.tenant_id, dataset_id, revision),
    ).fetchone()
    if rev is None:
        return _fail("not_found", "published revision not found")
    manifest = json.loads(rev["manifest"])
    return _ok({"dataset_id": dataset_id, "name": dataset["name"], "revision": revision, "columns": manifest.get("schema", {})})


def _analytics_query(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "dataset_id": args.get("dataset_id"),
        "dimensions": args.get("dimensions") or [],
        "measures": args.get("measures") or [],
        "filters": args.get("filters") or [],
        "limit": args.get("limit") or 200,
    }
    if args.get("revision") is not None:
        payload["revision"] = args["revision"]
    try:
        query = AnalyticsQuery.model_validate(payload)
    except ValueError as exc:
        return _fail("invalid_query", str(exc))
    result = run_query(ctx.store, ctx.objects, ctx.tenant_id, ctx.user, query).as_dict()
    return _ok(result, result.get("evidence_ref"))


def _metric_definitions(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or 50), 200))
    rows = ctx.store.conn.execute(
        "SELECT d.id, d.kind, p.version, p.semantic_release_id, p.effective_from "
        "FROM definition d LEFT JOIN definition_publication p "
        "ON p.tenant_id=d.tenant_id AND p.definition_id=d.id AND p.effective_to IS NULL "
        "WHERE d.tenant_id=? ORDER BY d.id ASC LIMIT ?",
        (ctx.tenant_id, limit),
    ).fetchall()
    definitions = []
    for row in rows:
        content = None
        if row["version"] is not None:
            version_row = ctx.store.conn.execute(
                "SELECT content FROM definition_version WHERE tenant_id=? AND definition_id=? AND version=?",
                (ctx.tenant_id, row["id"], row["version"]),
            ).fetchone()
            if version_row is not None:
                parsed = MetricDefinitionContent.model_validate(json.loads(version_row["content"]))
                content = {
                    "metric_id": parsed.metric_id,
                    "name": parsed.name,
                    "kind": parsed.kind,
                    "unit": parsed.unit,
                    "dataset_id": parsed.dataset_id,
                    "time_basis": parsed.time_basis,
                }
        definitions.append(
            {
                "metric_id": row["id"],
                "kind": row["kind"],
                "published_version": row["version"],
                "semantic_release_id": row["semantic_release_id"],
                "effective_from": row["effective_from"],
                "definition": content,
            }
        )
    return _ok({"metric_definitions": definitions, "count": len(definitions)})


def _metric_query(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    metric_id = args.get("metric_id")
    if not metric_id:
        return _fail("missing_field", "metric_id is required")
    window_start = args.get("window_start")
    window_end = args.get("window_end")
    if not window_start or not window_end:
        return _fail("missing_field", "window_start and window_end are required")

    publication = ctx.store.conn.execute(
        "SELECT * FROM definition_publication WHERE tenant_id=? AND definition_id=? AND effective_to IS NULL",
        (ctx.tenant_id, metric_id),
    ).fetchone()
    if publication is None:
        return _fail("metric_not_certified", "No approved definition version exists for this metric.")
    definition_row = ctx.store.conn.execute(
        "SELECT content FROM definition_version WHERE tenant_id=? AND definition_id=? AND version=?",
        (ctx.tenant_id, metric_id, publication["version"]),
    ).fetchone()
    if definition_row is None:
        return _fail("metric_not_certified", "Definition version content is unavailable.")
    definition = MetricDefinitionContent.model_validate(json.loads(definition_row["content"]))

    dataset = ctx.store.conn.execute(
        "SELECT * FROM dataset WHERE tenant_id=? AND id=?",
        (ctx.tenant_id, definition.dataset_id),
    ).fetchone()
    if dataset is None or dataset["published_revision"] is None:
        return _fail("no_published_revision", "The metric's dataset has no published revision.")
    revision_row = ctx.store.conn.execute(
        "SELECT manifest FROM dataset_revision WHERE tenant_id=? AND dataset_id=? AND revision=?",
        (ctx.tenant_id, dataset["id"], dataset["published_revision"]),
    ).fetchone()
    manifest = json.loads(revision_row["manifest"])

    request_payload = {
        "schema_version": "1.0",
        "metric_id": metric_id,
        "semantic_release_id": args.get("semantic_release_id") or publication["semantic_release_id"],
        "dimensions": args.get("dimensions") or [],
        "filters": args.get("filters") or [],
        "window": {
            "start": window_start,
            "end": window_end,
            "timezone": args.get("timezone") or definition.timezone,
        },
        "limit": args.get("limit") or 100,
    }
    try:
        request = MetricQueryRequest.model_validate(request_payload)
    except ValueError as exc:
        return _fail("invalid_query", str(exc))

    import io

    import polars as pl

    frame = pl.read_parquet(io.BytesIO(ctx.objects.get_revision_object(manifest["objects"][0]["key"])))
    plan = compile_plan(definition, request, dataset["published_revision"])
    rows, flags = execute(frame, definition, request, plan)
    evidence_ref = ctx.store.save_evidence(
        ctx.tenant_id,
        "metric_query",
        {"plan": plan, "rows": rows, "flags": flags, "source": "ai_tool"},
    )
    return _ok(
        {
            "metric_id": metric_id,
            "definition_version": publication["version"],
            "semantic_release_id": publication["semantic_release_id"],
            "window": request.window,
            "rows": rows,
            "row_count": len(rows),
            "quality_flags": flags,
            "executed_at": now_iso(),
        },
        evidence_ref,
    )


def _list_decisions_tool(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or 20), 100))
    status = args.get("status")
    records = list_decisions(ctx.store.conn, ctx.tenant_id, limit=limit)
    if status:
        records = [
            record
            for record in records
            if (record.status.value if hasattr(record.status, "value") else record.status) == status
        ]
    return _ok({"decisions": [_decision_dict(record) for record in records], "count": len(records)})


def _get_decision_tool(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    decision_id = args.get("decision_id")
    if not decision_id:
        return _fail("missing_field", "decision_id is required")
    record = get_decision(ctx.store.conn, ctx.tenant_id, decision_id)
    if record is None:
        return _fail("not_found", "decision not found")
    return _ok(_decision_dict(record))


def _monitoring_episodes(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or 20), 100))
    episodes = AlertLifecycle.list_episodes(ctx.tenant_id, ctx.store, args.get("status"))
    return _ok({"episodes": episodes[:limit], "count": min(len(episodes), limit)})


def _pilot_summary(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    pilot_id = args.get("pilot_id")
    if not pilot_id:
        return _fail("missing_field", "pilot_id is required")
    summary = pilot_summary(ctx.store, ctx.tenant_id, pilot_id)
    if summary is None:
        return _fail("not_found", "pilot not found")
    return _ok(summary)


def _predictive_score(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    model_id = args.get("model_id")
    if not model_id:
        return _fail("missing_field", "model_id is required")
    model = get_predictive_model(ctx.store, ctx.tenant_id, model_id)
    if model is None:
        return _fail(
            "model_not_trained",
            "No trained artifact exists for this model version; scoring is unavailable.",
            refused=True,
        )
    if model.get("status") != "active":
        return _fail(
            "model_not_active",
            f"Model status is '{model.get('status')}', expected 'active'; scoring is unavailable.",
            refused=True,
        )
    case_state, reason = evaluate_case_state(
        case_id=args.get("case_id") or "",
        observation_time_str=args.get("observation_time") or now_iso(),
        deadline_str=args.get("deadline"),
        current_status=args.get("current_status"),
    )
    if case_state.value != "eligible":
        return _fail(case_state.value, reason or "case is not eligible for scoring", refused=True)

    artifact_ref = model.get("model_artifact_path") or model.get("artifact")
    import os

    if not artifact_ref or not os.path.exists(str(artifact_ref)):
        return _fail(
            "model_not_trained",
            "No trained artifact exists for this model version; scoring is unavailable.",
            refused=True,
        )
    return _fail(
        "scoring_not_implemented",
        "A trained artifact exists but runtime scoring is not implemented in this build.",
        refused=True,
    )


TOOLS: dict[str, dict[str, Any]] = {
    "list_datasets": {
        "description": "List datasets in this tenant with their published revision and row count.",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
            "additionalProperties": False,
        },
        "handler": _list_datasets,
    },
    "dataset_schema": {
        "description": "Return the column schema of a dataset's published revision.",
        "parameters": {
            "type": "object",
            "properties": {"dataset_id": {"type": "string"}},
            "required": ["dataset_id"],
            "additionalProperties": False,
        },
        "handler": _dataset_schema,
    },
    "analytics_query": {
        "description": (
            "Run a bounded, read-only aggregation over a published dataset revision. "
            "Use this for counts, sums, averages and grouped breakdowns. Returns rows and an evidence_ref."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string"},
                "dimensions": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                "measures": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "agg": {"type": "string", "enum": ["count", "sum", "avg", "min", "max", "count_distinct"]},
                            "alias": {"type": "string"},
                        },
                        "required": ["column", "agg"],
                        "additionalProperties": False,
                    },
                },
                "filters": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "op": {
                                "type": "string",
                                "enum": ["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "is_null", "is_not_null"],
                            },
                            "value": {},
                        },
                        "required": ["column", "op"],
                        "additionalProperties": False,
                    },
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": ["dataset_id", "measures"],
            "additionalProperties": False,
        },
        "handler": _analytics_query,
    },
    "metric_definitions": {
        "description": "List certified metric definitions and their published versions.",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}},
            "additionalProperties": False,
        },
        "handler": _metric_definitions,
    },
    "metric_query": {
        "description": "Execute a certified metric over a time window. Returns rows and an evidence_ref.",
        "parameters": {
            "type": "object",
            "properties": {
                "metric_id": {"type": "string"},
                "window_start": {"type": "string"},
                "window_end": {"type": "string"},
                "timezone": {"type": "string"},
                "dimensions": {"type": "array", "items": {"type": "string"}},
                "filters": {"type": "array", "items": {"type": "object"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": ["metric_id", "window_start", "window_end"],
            "additionalProperties": False,
        },
        "handler": _metric_query,
    },
    "list_decisions": {
        "description": "List decisions in the register, optionally filtered by lifecycle status.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
        "handler": _list_decisions_tool,
    },
    "get_decision": {
        "description": "Fetch one decision record by id.",
        "parameters": {
            "type": "object",
            "properties": {"decision_id": {"type": "string"}},
            "required": ["decision_id"],
            "additionalProperties": False,
        },
        "handler": _get_decision_tool,
    },
    "monitoring_episodes": {
        "description": "List monitoring alert episodes, optionally filtered by workflow status.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
        "handler": _monitoring_episodes,
    },
    "pilot_summary": {
        "description": "Return the operational summary for a pilot by id.",
        "parameters": {
            "type": "object",
            "properties": {"pilot_id": {"type": "string"}},
            "required": ["pilot_id"],
            "additionalProperties": False,
        },
        "handler": _pilot_summary,
    },
    "predictive_score": {
        "description": (
            "Request a risk score for a case. Returns refused=true with a machine-readable code when "
            "the model is not trained or the case is ineligible; never returns an estimated score."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "model_id": {"type": "string"},
                "case_id": {"type": "string"},
                "deadline": {"type": "string"},
                "observation_time": {"type": "string"},
                "current_status": {"type": "string"},
            },
            "required": ["model_id", "case_id", "deadline"],
            "additionalProperties": False,
        },
        "handler": _predictive_score,
    },
}


def tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": spec["parameters"],
            },
        }
        for name, spec in TOOLS.items()
    ]


def execute_tool(ctx: ToolContext, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Execute a tool with tenant scoping, read permission, audit, and rate limiting."""
    spec = TOOLS.get(name)
    if spec is None:
        return _fail("unknown_tool", f"Unknown tool '{name}'.")
    if not has_permission(ctx.role, "read"):
        result = _fail("forbidden", "The current role does not have read permission.")
    elif ctx.rate_limited():
        result = _fail("rate_limited", "Tool rate limit exceeded. Retry shortly.")
    else:
        try:
            result = spec["handler"](ctx, arguments or {})
        except AnalyticsQueryError as exc:
            result = _fail(exc.code, exc.detail)
        except Exception as exc:  # noqa: BLE001 - tool failures are returned as data, not raised
            logger.exception("AI tool %s failed", name)
            result = _fail("tool_error", f"Tool '{name}' failed: {type(exc).__name__}")

    try:
        ctx.store.audit(
            ctx.tenant_id,
            ctx.user,
            f"ai.tool.{name}",
            str((arguments or {}).get("dataset_id") or (arguments or {}).get("metric_id") or name),
            "success" if result.get("ok") else "refused",
            {
                "ok": bool(result.get("ok")),
                "code": result.get("code"),
                "evidence_ref": result.get("evidence_ref"),
            },
        )
    except Exception:  # noqa: BLE001 - audit failure must not turn a tool refusal into a 500
        logger.exception("AI tool audit write failed for %s", name)
    return result



class ToolRegistry:
    """Thin registry facade used by the API layer and agent loop.

    Kept separate from module-level helpers so a caller can hold a registry
    bound to its own rate limiter without mutating global state.
    """

    def __init__(self, limiter: Any = None) -> None:
        self.limiter = limiter

    def schemas(self) -> list[dict[str, Any]]:
        return tool_schemas()

    def execute(self, ctx: ToolContext, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if ctx.limiter is None:
            ctx.limiter = self.limiter
        return execute_tool(ctx, name, arguments)
