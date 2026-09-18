from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from decisionos_analytics.execution import compile_plan, execute
from decisionos_analytics.semantics import MetricDefinitionContent, MetricQueryRequest

DF = pl.DataFrame({
    "originating_branch": ["A"] * 10 + ["B"] * 1000,
    "status": ["open"] * 1010,
    "created_at": ["2026-02-01T00:00:00Z"] * 1010,
    "first_response_at": ["2026-02-01T01:00:00Z"] * 9 + [""] * 1 + ["2026-02-01T01:00:00Z"] * 10 + [""] * 990,
})

RATIO = MetricDefinitionContent(
    metric_id="m.fr", name="first response rate", kind="ratio",
    expression={"kind": "ratio", "numerator_predicates": [{"op": "is_not_null", "field": "first_response_at"}]},
    eligibility=[], time_basis="created_at", timezone="Asia/Bahrain", dataset_id="ds",
)
REQ_ALL = MetricQueryRequest(schema_version="1.0", metric_id="m.fr", window={"start": "2026-01-01T00:00:00Z", "end": "2026-04-01T00:00:00Z", "timezone": "Asia/Bahrain"})
REQ_BRANCH = REQ_ALL.model_copy(update={"dimensions": ["originating_branch"]})


def test_ratio_is_ratio_of_totals_not_average_of_rates():  # QA-014
    plan = compile_plan(RATIO, REQ_ALL, 1)
    rows, flags = execute(DF, RATIO, REQ_ALL, plan)
    assert rows[0]["value"] == round(19 / 1010, 6)
    assert "ratio_computed_as_ratio_of_totals" in flags
    # the naive average of per-branch rates would be (0.9 + 0.01) / 2 = 0.455 — must NOT appear
    assert abs(rows[0]["value"] - 0.455) > 0.1


def test_grouped_ratio_of_totals():
    plan = compile_plan(RATIO, REQ_BRANCH, 1)
    rows, _ = execute(DF, RATIO, REQ_BRANCH, plan)
    got = {r["originating_branch"]: r["value"] for r in rows}
    assert got["A"] == 0.9 and got["B"] == 0.01


def test_zero_denominator_is_null_with_flag_not_silent_zero():
    defn = MetricDefinitionContent(
        metric_id="m.fr", name="zero den", kind="ratio",
        expression={"kind": "ratio", "denominator_predicates": [{"op": "eq", "field": "status", "value": "never-match"}]},
        eligibility=[], time_basis="created_at", timezone="Asia/Bahrain", dataset_id="ds",
    )
    plan = compile_plan(defn, REQ_BRANCH, 1)
    rows, flags = execute(DF, defn, REQ_BRANCH, plan)
    assert all(r["value"] is None for r in rows)
    assert "zero_denominator_returns_null" in flags


def test_window_is_half_open_in_business_timezone():  # QA-017
    df = pl.DataFrame({
        "originating_branch": ["A", "A"],
        "status": ["open", "open"],
        "created_at": ["2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z"],
        "first_response_at": ["2026-01-01T00:10:00Z", "2026-04-01T00:10:00Z"],
    })
    plan = compile_plan(RATIO, REQ_ALL, 1)
    rows, _ = execute(df, RATIO, REQ_ALL, plan)
    assert rows[0]["value"] == 1.0  # second row excluded: end is exclusive
