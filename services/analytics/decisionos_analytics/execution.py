"""Metric plan compilation and execution (spec §10.2–§10.4).

Compilation resolves: approved definition version -> dataset published revision ->
typed analytical plan. Execution uses Polars; ratios aggregate numerator and
denominator before division; windows are half-open [start, end) in the
definition's business timezone; zero denominators return null with a quality
flag — never a silent zero.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import polars as pl

from .semantics import (
    CountExpression,
    DurationPercentileExpression,
    MetricDefinitionContent,
    MetricQueryRequest,
    Predicate,
    RatioExpression,
)


def _pred(p: Predicate) -> pl.Expr:
    match p.op:
        case "is_not_null":
            return pl.col(p.field).is_not_null() & (pl.col(p.field) != "")
        case "is_null":
            return pl.col(p.field).is_null() | (pl.col(p.field) == "")
        case "eq":
            return pl.col(p.field) == p.value
        case "not_in":
            return ~pl.col(p.field).is_in(p.value)
        case "in":
            return pl.col(p.field).is_in(p.value)
        case "lt":
            return pl.col(p.field) < p.value
        case "gte":
            return pl.col(p.field) >= p.value
        case _:
            raise ValueError(f"unsupported predicate op {p.op}")


def _and(preds: list[Predicate]) -> pl.Expr:
    e = pl.lit(True)
    for p in preds:
        e = e & _pred(p)
    return e


def _count_where(preds: list[Predicate]) -> pl.Expr:
    if not preds:
        return pl.len()
    return _and(preds).cast(pl.Int64).sum()


def _to_utc(ts: str, tz_name: str) -> datetime:
    """Window bounds are business-timezone wall times; data timestamps are UTC.
    Bahrain has no DST; zoneinfo also handles zones that do (QA-017)."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt.astimezone(ZoneInfo("UTC"))


def _parse_ts(col: str) -> pl.Expr:
    return pl.col(col).str.slice(0, 19).str.to_datetime(strict=False)


def compile_plan(defn: MetricDefinitionContent, req: MetricQueryRequest, revision: int) -> dict:
    """The resolved analytical plan is a separate artifact from the request (§10.3)."""
    if req.metric_id != defn.metric_id:
        raise ValueError("metric identity mismatch")
    start = _to_utc(req.window["start"], defn.timezone)
    end = _to_utc(req.window["end"], defn.timezone)
    return {
        "plan_version": "1.0",
        "metric_id": defn.metric_id,
        "definition": defn.model_dump(),
        "source_binding": {"dataset_id": defn.dataset_id, "revision": revision},
        "time_basis_field": defn.time_basis,
        "window_utc": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "rule": "[start,end)",
        },
        "dimensions": req.dimensions,
        "extra_filters": [p.model_dump() for p in req.filters],
        "aggregation_stages": ["group", "ratio_of_totals"] if defn.kind == "ratio" else ["group", defn.kind],
    }


def execute(frame: pl.DataFrame, defn: MetricDefinitionContent, req: MetricQueryRequest, plan: dict) -> tuple[list[dict], list[str]]:
    flags: list[str] = []
    start = datetime.fromisoformat(plan["window_utc"]["start"]).replace(tzinfo=None)
    end = datetime.fromisoformat(plan["window_utc"]["end"]).replace(tzinfo=None)

    df = frame.with_columns(_parse_ts(defn.time_basis).alias("_tb"))
    df = df.filter(pl.col("_tb").is_not_null())
    df = df.filter((pl.col("_tb") >= start) & (pl.col("_tb") < end))
    for p in defn.eligibility:
        df = df.filter(_pred(p))
    for p in req.filters:
        df = df.filter(_pred(p))

    expr = defn.expression
    group = req.dimensions
    if isinstance(expr, RatioExpression):
        num = _count_where(expr.numerator_predicates)
        den = _count_where(expr.denominator_predicates)
        if group:
            res = df.group_by(group, maintain_order=True).agg(num.alias("_num"), den.alias("_den"))
        else:
            res = df.select(num.alias("_num"), den.alias("_den"))
        res = res.with_columns(
            pl.when(pl.col("_den") == 0).then(None).otherwise(pl.col("_num") / pl.col("_den")).alias("value")
        )
        if res.filter(pl.col("_den") == 0).height:
            flags.append("zero_denominator_returns_null")
        flags.append("ratio_computed_as_ratio_of_totals")
    elif isinstance(expr, DurationPercentileExpression):
        div = {"hours": 3600.0, "minutes": 60.0, "days": 86400.0}[expr.unit]
        dur = (_parse_ts(expr.end_field) - _parse_ts(expr.start_field)).dt.total_seconds() / div
        base = df.with_columns(dur.alias("_dur")).filter(pl.col("_dur").is_not_null())
        if group:
            res = base.group_by(group, maintain_order=True).agg(pl.col("_dur").quantile(expr.quantile, interpolation="linear").round(4).alias("value"), pl.len().alias("_n"))
        else:
            res = base.select(pl.col("_dur").quantile(expr.quantile, interpolation="linear").round(4).alias("value"), pl.len().alias("_n"))
        flags.append("exact_quantile_over_raw_values")
    elif isinstance(expr, CountExpression):
        cnt = _count_where(expr.predicates)
        res = df.group_by(group, maintain_order=True).agg(cnt.alias("value")) if group else df.select(cnt.alias("value"))
    else:  # pragma: no cover
        raise ValueError("unsupported expression")

    rows = res.limit(req.limit).sort(group if group else ["value"]).to_dicts()
    out = []
    for r in rows:
        clean = {k: v for k, v in r.items() if not k.startswith("_")}
        if isinstance(clean.get("value"), float):
            clean["value"] = round(clean["value"], 6)
        out.append(clean)
    return out, flags
