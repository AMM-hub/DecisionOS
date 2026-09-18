"""Semantic definition model: stable identities, immutable content versions,
publications with business-effective intervals (spec §10.1, §22.3).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator


class Predicate(BaseModel):
    """Structured, whitelisted filter — never free-text SQL (§10.3)."""

    op: Literal["is_not_null", "is_null", "eq", "not_in", "in", "lt", "gte"]
    field: str
    value: object | None = None

    @field_validator("op")
    @classmethod
    def _known_op(cls, v: str) -> str:
        assert v in {"is_not_null", "is_null", "eq", "not_in", "in", "lt", "gte"}
        return v


class RatioExpression(BaseModel):
    kind: Literal["ratio"]
    numerator: Literal["count"] = "count"
    numerator_predicates: list[Predicate] = []
    denominator_predicates: list[Predicate] = []


class DurationPercentileExpression(BaseModel):
    kind: Literal["duration_percentile"]
    start_field: str
    end_field: str
    unit: Literal["hours", "minutes", "days"] = "hours"
    quantile: float = 0.5

    @field_validator("quantile")
    @classmethod
    def _q(cls, v: float) -> float:
        assert 0.0 < v < 1.0, "quantile must be in (0,1)"
        return v


class CountExpression(BaseModel):
    kind: Literal["count"]
    predicates: list[Predicate] = []


Expression = RatioExpression | DurationPercentileExpression | CountExpression


class MetricDefinitionContent(BaseModel):
    metric_id: str
    name: str
    kind: Literal["ratio", "count", "duration_percentile"]
    expression: Expression
    eligibility: list[Predicate]          # eligible population
    time_basis: str                        # field the window applies to
    timezone: str = "Asia/Bahrain"
    unit: str | None = None
    zero_denominator: Literal["null_with_flag"] = "null_with_flag"  # never silently zero (§10.2)
    dataset_id: str

    @field_validator("metric_id")
    @classmethod
    def _stable_id(cls, v: str) -> str:
        assert v and " " not in v, "metric_id must be a stable identifier"
        return v


class MetricQueryRequest(BaseModel):
    schema_version: Literal["1.0"]
    metric_id: str
    semantic_release_id: str | None = None
    dimensions: list[str] = []
    filters: list[Predicate] = []
    window: dict  # {start, end, timezone}
    limit: int = 100

    @field_validator("window")
    @classmethod
    def _window(cls, v: dict) -> dict:
        for k in ("start", "end", "timezone"):
            assert k in v, f"window.{k} required"
        return v
