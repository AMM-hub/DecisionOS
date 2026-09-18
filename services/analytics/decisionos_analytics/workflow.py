"""M3 Workflow Analytics (spec §15 — Workflow and Process Intelligence).

Event histories (case, activity, timestamp) are loaded into a PM4Py event log
and analyzed for: bottlenecks, variants, conformance against expected
transition rules, case-level SLA metrics, and stage throughput times.

Design principles encoded here:
1. Unknown event types are preserved, never silently dropped: every activity
   value in the log participates in variants and throughput, and activities
   that the expected-rules model does not know about are reported explicitly
   as ``unknown_activities`` in conformance results.
2. Durations are computed only between consecutive events of the same case;
   the last event of a case has no exit timestamp and is excluded from
   duration statistics (but still counted) — never imputed.
3. Refusal is a first-class outcome: missing columns or empty logs raise
   WorkflowError, which the API maps to insufficient_data — never a
   fabricated analysis.

PM4Py (community edition, AGPL) is used for the event-log object model and
variant extraction; the numerical analyses are plain polars so results are
deterministic and unit-testable.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone

import pandas as pd
import polars as pl

CASE_COL, EVENT_COL, TS_COL = "case_id", "event", "timestamp"
PM_CASE, PM_EVENT, PM_TS = "case:concept:name", "concept:name", "time:timestamp"

UNIT_SECONDS = {"seconds": 1.0, "minutes": 60.0, "hours": 3600.0, "days": 86400.0}
DEFAULT_CLOSED_ACTIVITIES = {"closed", "resolved", "completed", "done", "cancelled"}


class WorkflowError(ValueError):
    """Input cannot support a workflow analysis (spec §15 refusal path)."""


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def _ts_column(data: pl.DataFrame, col: str) -> pl.Expr:
    dtype = data.schema[col]
    if dtype == pl.Utf8:
        # ISO-8601 with optional 'Z'/fractional seconds; naive UTC (QA-017 style
        # normalization matching execution._parse_ts)
        return pl.col(col).str.slice(0, 19).str.to_datetime(strict=False)
    if isinstance(dtype, pl.Datetime) and dtype.time_zone:
        return pl.col(col).dt.convert_time_zone("UTC").dt.replace_time_zone(None)
    return pl.col(col).cast(pl.Datetime, strict=False)


def load_event_log(
    data: pl.DataFrame | pd.DataFrame,
    case_id_col: str = CASE_COL,
    event_col: str = EVENT_COL,
    timestamp_col: str = TS_COL,
    attribute_cols: list[str] | None = None,
):
    """Polars/pandas event table -> PM4Py EventLog (traces sorted by time).

    Rows with null case/activity/timestamp are excluded from the log (they
    cannot be ordered); everything else — including event types we have never
    seen — is preserved (§15 requirement 6).
    """
    if isinstance(data, pd.DataFrame):
        data = pl.from_pandas(data)
    if not isinstance(data, pl.DataFrame):
        raise WorkflowError("event data must be a polars or pandas DataFrame")
    missing = [c for c in (case_id_col, event_col, timestamp_col) if c not in data.columns]
    if missing:
        raise WorkflowError(f"missing required columns: {missing}")

    attrs = [c for c in (attribute_cols or []) if c in data.columns and c not in (case_id_col, event_col, timestamp_col)]
    f = data.with_columns(
        pl.col(case_id_col).cast(pl.Utf8).alias(CASE_COL),
        pl.col(event_col).cast(pl.Utf8).alias(EVENT_COL),
        _ts_column(data, timestamp_col).alias(TS_COL),
    )
    f = f.drop_nulls([CASE_COL, EVENT_COL, TS_COL]).sort([CASE_COL, TS_COL])
    if f.height == 0:
        raise WorkflowError("no usable events (all rows have null case, event, or timestamp)")

    from pm4py.objects.log.obj import EventLog, Trace

    log = EventLog()
    for (cid,), sub in f.group_by(CASE_COL, maintain_order=True):
        trace = Trace()
        trace.attributes[PM_CASE] = cid
        for row in sub.select([EVENT_COL, TS_COL, *attrs]).iter_rows(named=True):
            ev = {PM_EVENT: row[EVENT_COL], PM_TS: row[TS_COL]}
            for a in attrs:
                if row[a] is not None:
                    ev[a] = row[a]
            trace.append(ev)
        log.append(trace)
    log.attributes[PM_CASE] = CASE_COL
    return log


def _as_frame(log) -> pl.DataFrame:
    """Normalize EventLog | pandas | polars (canonical columns) -> polars frame."""
    if isinstance(log, pd.DataFrame):
        log = pl.from_pandas(log)
    if isinstance(log, pl.DataFrame):
        missing = [c for c in (CASE_COL, EVENT_COL, TS_COL) if c not in log.columns]
        if missing:
            raise WorkflowError(f"frame missing canonical columns {missing}; call load_event_log first")
        f = log.with_columns(
            pl.col(CASE_COL).cast(pl.Utf8),
            pl.col(EVENT_COL).cast(pl.Utf8),
            _ts_column(log, TS_COL).alias(TS_COL),
        ).drop_nulls([CASE_COL, EVENT_COL, TS_COL]).sort([CASE_COL, TS_COL])
    else:  # PM4Py EventLog
        rows = []
        for trace in log:
            cid = trace.attributes.get(PM_CASE) or getattr(trace, "case_id", None) or str(trace)
            for ev in trace:
                ts = ev.get(PM_TS)
                if isinstance(ts, pd.Timestamp):
                    ts = ts.to_pydatetime()
                if ts is not None and ts.tzinfo is not None:
                    ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
                rows.append((str(cid), str(ev.get(PM_EVENT)), ts))
        f = pl.DataFrame(rows, schema={CASE_COL: pl.Utf8, EVENT_COL: pl.Utf8, TS_COL: pl.Datetime}, orient="row")
        f = f.drop_nulls().sort([CASE_COL, TS_COL])
    if f.height == 0:
        raise WorkflowError("empty event log")
    return f


def _with_durations(f: pl.DataFrame) -> pl.DataFrame:
    """waiting_s = since previous event in case; duration_s = until next event."""
    return f.with_columns(
        pl.col(TS_COL).diff().over(CASE_COL).dt.total_seconds().alias("waiting_s"),
        (-pl.col(TS_COL).diff(-1).over(CASE_COL)).dt.total_seconds().alias("duration_s"),
        pl.col(EVENT_COL).shift(-1).over(CASE_COL).alias("_next_event"),
        pl.col(EVENT_COL).shift(1).over(CASE_COL).alias("_prev_event"),
    )


def _num(x: float | None, nd: int = 3) -> float | None:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd)


def _unit_div(unit: str) -> float:
    if unit not in UNIT_SECONDS:
        raise WorkflowError(f"unsupported unit '{unit}'; use one of {sorted(UNIT_SECONDS)}")
    return UNIT_SECONDS[unit]


def _traces(f: pl.DataFrame) -> list[tuple[str, list[str]]]:
    return [
        (cid, sub[EVENT_COL].to_list())
        for (cid,), sub in f.sort([CASE_COL, TS_COL]).group_by(CASE_COL, maintain_order=True)
    ]


# ---------------------------------------------------------------------------
# bottleneck analysis
# ---------------------------------------------------------------------------

def bottleneck_analysis(log, unit: str = "hours") -> list[dict]:
    """Per activity: count, median/avg duration in stage, median waiting time.

    Sorted by longest median duration first — the stage where cases wait
    longest is the bottleneck (§15 requirement 2). Last events of a case have
    no exit timestamp and are excluded from duration stats, never imputed.
    """
    div = _unit_div(unit)
    f = _with_durations(_as_frame(log))
    out = []
    for (act,), sub in f.group_by(EVENT_COL, maintain_order=True):
        dur = (sub["duration_s"] / div).drop_nulls()
        wait = (sub["waiting_s"] / div).drop_nulls()
        out.append({
            "activity": act,
            "count": sub.height,
            "median": _num(dur.median()) if dur.len() else None,
            "avg": _num(dur.mean()) if dur.len() else None,
            "waiting_time": _num(wait.median()) if wait.len() else None,
        })
    out.sort(key=lambda r: (r["median"] is None, -(r["median"] or 0)))
    return out


# ---------------------------------------------------------------------------
# variant analysis
# ---------------------------------------------------------------------------

def variant_analysis(log) -> list[dict]:
    """Group cases by their full activity sequence (§15 requirement 3).

    Returns all variants sorted by case count; ``simplified_path`` collapses
    consecutive repeats so loop-heavy paths stay readable.
    """
    f = _as_frame(log)
    traces = _traces(f)
    total = len(traces)
    counts: Counter[tuple[str, ...]] = Counter(tuple(evts) for _, evts in traces)
    out = []
    for path, n in counts.most_common():
        simplified = [a for i, a in enumerate(path) if i == 0 or a != path[i - 1]]
        out.append({
            "path": list(path),
            "simplified_path": simplified,
            "case_count": n,
            "frequency": _num(n / total, 4),
        })
    return out


# ---------------------------------------------------------------------------
# conformance checking
# ---------------------------------------------------------------------------

def conformance_checking(log, expected_rules: list[dict]) -> dict:
    """Check actual flows against allowed {from_activity, to_activity}
    transitions (§15 requirement 4).

    - fitness: share of cases whose every consecutive transition is allowed
    - precision: share of the model's allowed transitions actually observed
      (how much of the expected process the data justifies)
    - unknown_activities: event types the rules never mention — preserved and
      reported, never silently dropped
    """
    rules = []
    for r in expected_rules or []:
        src, dst = r.get("from_activity"), r.get("to_activity")
        if src and dst:
            rules.append((str(src), str(dst)))
    if not rules:
        raise WorkflowError("expected_rules must contain at least one {from_activity, to_activity} pair")
    allowed = set(rules)

    f = _as_frame(log)
    traces = _traces(f)
    violations: list[dict] = []
    violated_cases = 0
    observed: set[tuple[str, str]] = set()
    all_activities: set[str] = set(f[EVENT_COL].unique().to_list())
    rule_activities = {a for pair in allowed for a in pair}

    for cid, evts in traces:
        bad = 0
        for src, dst in zip(evts, evts[1:]):
            if (src, dst) in allowed:
                observed.add((src, dst))
            else:
                bad += 1
                violations.append({"case_id": cid, "from": src, "to": dst})
        if bad:
            violated_cases += 1

    return {
        "fitness": _num((len(traces) - violated_cases) / len(traces), 4),
        "precision": _num(len(observed) / len(allowed), 4),
        "violated_cases": violated_cases,
        "total_cases": len(traces),
        "example_violations": violations[:10],
        "unknown_activities": sorted(all_activities - rule_activities),
    }


# ---------------------------------------------------------------------------
# case metrics / SLA
# ---------------------------------------------------------------------------

def case_metrics(
    data,
    sla_hours: float = 48.0,
    unit: str = "hours",
    now: str | datetime | None = None,
    closed_activities: set[str] | None = None,
) -> dict:
    """Per-case age, duration, stage count, current stage, SLA status
    (§15 requirement 5).

    A case is closed when its last event is one of ``closed_activities``;
    open cases age against ``now`` (default: the latest timestamp in the
    data, so results are deterministic without a wall clock).
    """
    div = _unit_div(unit)
    closed = set(closed_activities or DEFAULT_CLOSED_ACTIVITIES)
    f = _as_frame(data)
    if isinstance(now, str):
        now = datetime.fromisoformat(now.replace("Z", "+00:00")).replace(tzinfo=None)
    as_of = now or f[TS_COL].max()

    out = []
    grouped = f.sort([CASE_COL, TS_COL]).group_by(CASE_COL, maintain_order=True).agg(
        pl.col(TS_COL).min().alias("first_ts"),
        pl.col(TS_COL).max().alias("last_ts"),
        pl.col(EVENT_COL).last().alias("current"),
        pl.col(EVENT_COL).n_unique().alias("stage_count"),
    )
    for row in grouped.iter_rows(named=True):
        duration_h = (row["last_ts"] - row["first_ts"]).total_seconds() / 3600.0
        is_closed = row["current"] in closed
        age_h = duration_h if is_closed else (as_of - row["first_ts"]).total_seconds() / 3600.0
        if is_closed:
            sla_status = "met" if duration_h <= sla_hours else "breached"
        else:
            sla_status = "in_progress" if age_h <= sla_hours else "breached"
        out.append({
            "case_id": row[CASE_COL],
            "duration": _num((row["last_ts"] - row["first_ts"]).total_seconds() / div),
            "age": _num(age_h * 3600.0 / div),
            "stage_count": row["stage_count"],
            "current": row["current"],
            "closed": is_closed,
            "overdue": sla_status == "breached",
            "sla_status": sla_status,
        })
    out.sort(key=lambda r: (-r["age"] if r["age"] is not None else 0, r["case_id"]))
    return {
        "metrics": out,
        "sla_hours": sla_hours,
        "unit": unit,
        "as_of": as_of.isoformat(),
        "summary": {
            "total_cases": len(out),
            "met": sum(1 for r in out if r["sla_status"] == "met"),
            "in_progress": sum(1 for r in out if r["sla_status"] == "in_progress"),
            "breached": sum(1 for r in out if r["sla_status"] == "breached"),
        },
    }


# ---------------------------------------------------------------------------
# throughput times
# ---------------------------------------------------------------------------

def throughput_times(log, unit: str = "hours", top_n: int = 5) -> list[dict]:
    """Per stage: min/median/max/p90 time-in-stage plus entry and exit
    neighborhoods with counts (§15 workflow throughput view).

    Time-in-stage is the gap to the next event of the same case; the final
    event of each case has no exit and is excluded from the time stats.
    """
    div = _unit_div(unit)
    f = _with_durations(_as_frame(log))
    out = []
    for (act,), sub in f.group_by(EVENT_COL, maintain_order=True):
        dur = (sub["duration_s"] / div).drop_nulls()
        frm = Counter(sub["_prev_event"].drop_nulls().to_list()).most_common(top_n)
        to = Counter(sub["_next_event"].drop_nulls().to_list()).most_common(top_n)
        out.append({
            "stage": act,
            "count": sub.height,
            "min": _num(dur.min()) if dur.len() else None,
            "median": _num(dur.median()) if dur.len() else None,
            "max": _num(dur.max()) if dur.len() else None,
            "p90": _num(dur.quantile(0.9)) if dur.len() else None,
            "from_activities": dict(frm),
            "to_activities": dict(to),
        })
    out.sort(key=lambda r: (r["median"] is None, -(r["median"] or 0)))
    return out
