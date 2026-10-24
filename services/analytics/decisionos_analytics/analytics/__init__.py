"""Bounded, read-only dataset analytics over published revisions."""

from .query import (
    AnalyticsQuery,
    AnalyticsQueryError,
    FilterSpec,
    MeasureSpec,
    run_query,
)

__all__ = [
    "AnalyticsQuery",
    "AnalyticsQueryError",
    "FilterSpec",
    "MeasureSpec",
    "run_query",
]
