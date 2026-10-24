"""Bounded structured queries over a tenant's published dataset revision.

The query vocabulary is deliberately small and closed: dimensions, measures,
filters, an optional time window, ordering and a hard row cap. Column names are
validated against the revision manifest before they reach Polars, so no
free-form expression or SQL ever reaches execution.
"""

from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, Field, model_validator

from ..evidence import compute_canonical_digest
from ..objectstore import LocalObjectStore
from ..store import Store, new_id, now_iso

Aggregation = Literal["count", "sum", "avg", "min", "max", "count_distinct"]
FilterOperator = Literal[
    "eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "is_null", "is_not_null"
]


class MeasureSpec(BaseModel):
    column: str = Field(min_length=1)
    agg: Aggregation
    alias: str | None = None


class FilterSpec(BaseModel):
    column: str = Field(min_length=1)
    op: FilterOperator
    value: Any = None


class AnalyticsQuery(BaseModel):
    dataset_id: str = Field(min_length=1)
    revision: int | None = Field(default=None, ge=1)
    dimensions: list[str] = Field(default_factory=list, max_length=3)
    measures: list[MeasureSpec] = Field(min_length=1, max_length=4)
    filters: list[FilterSpec] = Field(default_factory=list, max_length=5)
    time_column: str | None = None
    time_from: str | None = None
    time_to: str | None = None
    limit: int = Field(default=200, ge=1, le=500)
    order_by: str | None = None
    order_dir: Literal["asc", "desc"] = "asc"

    @model_validator(mode="after")
    def _check_shape(self) -> AnalyticsQuery:
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("dimensions must be unique")
        for measure in self.measures:
            if measure.column == "*" and measure.agg != "count":
                raise ValueError(f"measure '{measure.agg}' requires a concrete column")
            if measure.alias is not None and not measure.alias.strip():
                raise ValueError("measure alias must not be blank")
        if (self.time_from or self.time_to) and not self.time_column:
            raise ValueError("time_column is required when a time window is supplied")
        return self


class AnalyticsQueryError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        self.status = status
        self.code = code
        self.detail = detail
        super().__init__(detail)


@dataclass
class ResolvedRevision:
    dataset_id: str
    revision: int
    schema: dict[str, str]
    manifest: dict[str, Any]


@dataclass
class ExecutedQuery:
    dataset_id: str
    revision: int
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    evidence_ref: str
    executed_at: str
    took_ms: int
    result_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "revision": self.revision,
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "evidence_ref": self.evidence_ref,
            "executed_at": self.executed_at,
            "took_ms": self.took_ms,
        }


def resolve_revision(store: Store, tenant: str, query: AnalyticsQuery) -> ResolvedRevision:
    dataset = store.conn.execute(
        "SELECT * FROM dataset WHERE tenant_id=? AND id=?", (tenant, query.dataset_id)
    ).fetchone()
    if dataset is None:
        raise AnalyticsQueryError(404, "not_found", "not found")

    revision_no = query.revision if query.revision is not None else dataset["published_revision"]
    if revision_no is None:
        raise AnalyticsQueryError(
            409, "revision_not_published", "No published revision exists for this dataset."
        )

    revision = store.conn.execute(
        "SELECT * FROM dataset_revision WHERE tenant_id=? AND dataset_id=? AND revision=?",
        (tenant, query.dataset_id, revision_no),
    ).fetchone()
    if revision is None or revision["state"] != "published":
        raise AnalyticsQueryError(
            409,
            "revision_not_published",
            f"Revision {revision_no} is not published for this dataset.",
        )

    manifest = json.loads(revision["manifest"])
    schema = manifest.get("schema") or {}
    if not isinstance(schema, dict):
        schema = {}
    return ResolvedRevision(query.dataset_id, int(revision_no), schema, manifest)


def _validate_column(column: str, schema: dict[str, str], revision: int) -> None:
    if column not in schema:
        raise AnalyticsQueryError(
            422,
            "unknown_column",
            f"Unknown column '{column}' for dataset revision {revision}.",
        )


def _output_names(query: AnalyticsQuery) -> tuple[list[str], list[str]]:
    dimensions = list(query.dimensions)
    measures: list[str] = []
    for measure in query.measures:
        if measure.alias:
            name = measure.alias.strip()
        elif measure.agg == "count" and measure.column == "*":
            name = "count"
        else:
            name = f"{measure.agg}_{measure.column}"
        measures.append(name)
    if len(set(measures)) != len(measures):
        raise AnalyticsQueryError(422, "invalid_query", "Measure output names must be unique.")
    if set(dimensions) & set(measures):
        raise AnalyticsQueryError(422, "invalid_query", "Measure output names must not collide with dimensions.")
    return dimensions, measures


def _validate_columns(query: AnalyticsQuery, resolved: ResolvedRevision) -> None:
    schema = resolved.schema
    for dimension in query.dimensions:
        _validate_column(dimension, schema, resolved.revision)
    for measure in query.measures:
        if measure.column != "*":
            _validate_column(measure.column, schema, resolved.revision)
    for predicate in query.filters:
        _validate_column(predicate.column, schema, resolved.revision)
        if predicate.op in ("in", "not_in") and not isinstance(predicate.value, (list, tuple, set)):
            raise AnalyticsQueryError(
                422, "invalid_filter", f"Filter '{predicate.column}' with op '{predicate.op}' requires a list value."
            )
    if query.time_column:
        _validate_column(query.time_column, schema, resolved.revision)


def _filter_expression(predicate: FilterSpec) -> pl.Expr:
    column = pl.col(predicate.column)
    match predicate.op:
        case "eq":
            return column == predicate.value
        case "neq":
            return column != predicate.value
        case "in":
            return column.is_in(list(predicate.value))
        case "not_in":
            return ~column.is_in(list(predicate.value))
        case "gt":
            return column > predicate.value
        case "gte":
            return column >= predicate.value
        case "lt":
            return column < predicate.value
        case "lte":
            return column <= predicate.value
        case "is_null":
            return column.is_null()
        case "is_not_null":
            return column.is_not_null()
        case _:  # pragma: no cover - Literal prevents this
            raise AnalyticsQueryError(422, "invalid_filter", f"Unsupported filter op '{predicate.op}'.")


def _measure_expression(measure: MeasureSpec, output_name: str) -> pl.Expr:
    if measure.agg == "count":
        expression = pl.len() if measure.column == "*" else pl.col(measure.column).is_not_null().sum()
    elif measure.agg == "count_distinct":
        expression = pl.col(measure.column).n_unique()
    elif measure.agg == "sum":
        expression = pl.col(measure.column).sum()
    elif measure.agg == "avg":
        expression = pl.col(measure.column).mean()
    elif measure.agg == "min":
        expression = pl.col(measure.column).min()
    elif measure.agg == "max":
        expression = pl.col(measure.column).max()
    else:  # pragma: no cover - Literal prevents this
        raise AnalyticsQueryError(422, "invalid_query", f"Unsupported aggregation '{measure.agg}'.")
    return expression.alias(output_name)


def _parse_bound(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AnalyticsQueryError(422, "invalid_time_window", f"Invalid {label}: '{value}'.") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and value != value:
        return None
    return value


def _column_types(query: AnalyticsQuery, dimensions: list[str], measures: list[str], schema: dict[str, str]) -> list[dict[str, str]]:
    columns = [{"name": name, "type": schema.get(name, "string")} for name in dimensions]
    for measure, name in zip(query.measures, measures, strict=True):
        if measure.agg in ("count", "count_distinct"):
            kind = "integer"
        elif measure.agg in ("sum", "avg"):
            kind = "number"
        else:
            kind = schema.get(measure.column, "number") if measure.column != "*" else "number"
        columns.append({"name": name, "type": kind})
    return columns


def _record_evidence(
    store: Store,
    tenant: str,
    user: str,
    query: AnalyticsQuery,
    result: ExecutedQuery,
) -> str:
    evidence_ref = f"ev-{new_id()[:12]}"
    payload = {
        "dataset_id": result.dataset_id,
        "revision": result.revision,
        "query": query.model_dump(),
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "result_digest": result.result_digest,
        "took_ms": result.took_ms,
    }
    store.conn.execute(
        "INSERT INTO evidence(tenant_id, id, kind, payload, created_at) VALUES (?,?,?,?,?)",
        (tenant, evidence_ref, "analytics_query", json.dumps(payload, default=str), now_iso()),
    )
    store.conn.commit()
    store.audit(
        tenant,
        user,
        "analytics.query",
        f"{result.dataset_id}@r{result.revision}",
        "answered",
        {"evidence_ref": evidence_ref, "row_count": result.row_count, "truncated": result.truncated},
    )
    return evidence_ref


def run_query(
    store: Store,
    objects: LocalObjectStore,
    tenant: str,
    user: str,
    query: AnalyticsQuery,
) -> ExecutedQuery:
    started = time.perf_counter()
    resolved = resolve_revision(store, tenant, query)
    _validate_columns(query, resolved)
    dimensions, measure_names = _output_names(query)

    if query.order_by and query.order_by not in set(dimensions) | set(measure_names):
        raise AnalyticsQueryError(
            422, "unknown_column", f"Unknown output column '{query.order_by}' in order_by."
        )

    needed = set(query.dimensions)
    needed.update(m.column for m in query.measures if m.column != "*")
    needed.update(f.column for f in query.filters)
    if query.time_column:
        needed.add(query.time_column)

    parquet = objects.get_revision_object(resolved.manifest["objects"][0]["key"])
    frame = pl.read_parquet(io.BytesIO(parquet), columns=sorted(needed)) if needed else pl.read_parquet(io.BytesIO(parquet))

    for predicate in query.filters:
        frame = frame.filter(_filter_expression(predicate))

    if query.time_column and (query.time_from or query.time_to):
        time_expr = pl.col(query.time_column)
        if frame.schema[query.time_column] == pl.Utf8:
            time_expr = time_expr.str.to_datetime(strict=False)
        else:
            time_expr = time_expr.cast(pl.Datetime, strict=False)
        frame = frame.with_columns(time_expr.alias("__time_window"))
        frame = frame.filter(pl.col("__time_window").is_not_null())
        if query.time_from:
            frame = frame.filter(pl.col("__time_window") >= _parse_bound(query.time_from, "time_from"))
        if query.time_to:
            frame = frame.filter(pl.col("__time_window") <= _parse_bound(query.time_to, "time_to"))
        frame = frame.drop("__time_window")

    measure_expressions = [
        _measure_expression(measure, name)
        for measure, name in zip(query.measures, measure_names, strict=True)
    ]
    try:
        if dimensions:
            result_frame = frame.group_by(dimensions, maintain_order=True).agg(measure_expressions)
        else:
            result_frame = frame.select(measure_expressions)
    except pl.exceptions.PolarsError as exc:
        raise AnalyticsQueryError(422, "query_execution_failed", f"Query could not be executed: {exc}") from exc

    order_columns: list[tuple[str, bool]] = []
    if query.order_by:
        order_columns.append((query.order_by, query.order_dir == "desc"))
    for dimension in dimensions:
        if all(name != dimension for name, _ in order_columns):
            order_columns.append((dimension, False))
    if order_columns:
        result_frame = result_frame.sort(
            [name for name, _ in order_columns],
            descending=[descending for _, descending in order_columns],
            nulls_last=True,
        )

    truncated = result_frame.height > query.limit
    result_frame = result_frame.head(query.limit)
    result_frame = result_frame.select([*dimensions, *measure_names])
    rows = [[_jsonable(row.get(name)) for name in [*dimensions, *measure_names]] for row in result_frame.iter_rows(named=True)]

    result = ExecutedQuery(
        dataset_id=resolved.dataset_id,
        revision=resolved.revision,
        columns=_column_types(query, dimensions, measure_names, resolved.schema),
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        evidence_ref="",
        executed_at=now_iso(),
        took_ms=int((time.perf_counter() - started) * 1000),
        result_digest=compute_canonical_digest(rows),
    )
    result.evidence_ref = _record_evidence(store, tenant, user, query, result)
    return result
