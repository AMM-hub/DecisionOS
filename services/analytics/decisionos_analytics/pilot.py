"""PILOT-01 Controlled Operational Pilot Contract, Readiness Gate & Governance.

Manages pilot configuration, status transitions, data readiness validation,
and Support Operations semantic pack definitions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import polars as pl

from .store import Store, new_id, now_iso


class PilotStatus(str, Enum):
    DRAFT = "draft"
    CONFIGURATION = "configuration"
    READY_FOR_EVALUATION = "ready_for_evaluation"
    ACTIVE = "active"
    REVIEW = "review"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


VALID_PILOT_TRANSITIONS: dict[PilotStatus, set[PilotStatus]] = {
    PilotStatus.DRAFT: {PilotStatus.CONFIGURATION, PilotStatus.ABANDONED},
    PilotStatus.CONFIGURATION: {PilotStatus.READY_FOR_EVALUATION, PilotStatus.ABANDONED},
    PilotStatus.READY_FOR_EVALUATION: {PilotStatus.ACTIVE, PilotStatus.CONFIGURATION, PilotStatus.ABANDONED},
    PilotStatus.ACTIVE: {PilotStatus.REVIEW, PilotStatus.ABANDONED},
    PilotStatus.REVIEW: {PilotStatus.COMPLETED, PilotStatus.ACTIVE, PilotStatus.ABANDONED},
    PilotStatus.COMPLETED: set(),
    PilotStatus.ABANDONED: set(),
}


@dataclass
class PilotContract:
    id: str
    tenant_id: str
    name: str
    domain: str = "support_ticket_operations"
    owner: str = "ops.manager"
    status: PilotStatus = PilotStatus.DRAFT
    dataset_id: str | None = None
    dataset_revision: int | None = None
    timezone: str = "UTC"
    time_basis: str = "calendar_utc"
    started_at: str | None = None
    target_end_at: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    created_by: str = "system"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "domain": self.domain,
            "owner": self.owner,
            "status": self.status.value if isinstance(self.status, PilotStatus) else self.status,
            "dataset_id": self.dataset_id,
            "dataset_revision": self.dataset_revision,
            "timezone": self.timezone,
            "time_basis": self.time_basis,
            "started_at": self.started_at,
            "target_end_at": self.target_end_at,
            "config": self.config,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# Standard Support Operations Semantic Pack Definitions
SUPPORT_OPERATIONS_SEMANTIC_PACK: list[dict[str, Any]] = [
    {
        "id": "m_ticket_count",
        "name": "Ticket Volume",
        "kind": "count",
        "unit": "tickets",
        "description": "Total count of support ticket events in the measurement window.",
        "version": 1,
    },
    {
        "id": "m_sla_breach_rate",
        "name": "24h SLA Breach Rate",
        "kind": "ratio",
        "unit": "percent",
        "description": "Percentage of tickets exceeding the 24h SLA resolution deadline.",
        "version": 1,
    },
    {
        "id": "m_avg_resolution_hours",
        "name": "Average Resolution Time",
        "kind": "average",
        "unit": "hours",
        "description": "Mean hours elapsed from ticket creation to final resolution.",
        "version": 1,
    },
    {
        "id": "m_queue_backlog",
        "name": "Queue Backlog Count",
        "kind": "count",
        "unit": "tickets",
        "description": "Count of open unresolved tickets currently in queue.",
        "version": 1,
    },
    {
        "id": "m_reopen_rate",
        "name": "Ticket Reopen Rate",
        "kind": "ratio",
        "unit": "percent",
        "description": "Percentage of resolved tickets reopened within 7 days.",
        "version": 1,
    },
]


def create_pilot(
    store: Store,
    tenant_id: str,
    name: str,
    owner: str,
    domain: str = "support_ticket_operations",
    dataset_id: str | None = None,
    dataset_revision: int | None = None,
    timezone_str: str = "UTC",
    time_basis: str = "calendar_utc",
    config: dict[str, Any] | None = None,
    user_id: str = "system",
) -> dict[str, Any]:
    """Create a new bounded pilot contract."""
    pilot_id = f"plt-{new_id()[:12]}"
    ts = now_iso()
    config = config or {}

    store.conn.execute(
        """INSERT INTO pilot(
            tenant_id, id, name, domain, owner, status, dataset_id, dataset_revision,
            timezone, time_basis, started_at, target_end_at, config_json, created_by, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            tenant_id,
            pilot_id,
            name,
            domain,
            owner,
            PilotStatus.DRAFT.value,
            dataset_id,
            dataset_revision,
            timezone_str,
            time_basis,
            ts,
            None,
            json.dumps(config),
            user_id,
            ts,
            ts,
        ),
    )
    store.conn.commit()
    return get_pilot(store, tenant_id, pilot_id)  # type: ignore[return-value]


def get_pilot(store: Store, tenant_id: str, pilot_id: str) -> dict[str, Any] | None:
    row = store.conn.execute(
        "SELECT * FROM pilot WHERE tenant_id=? AND id=?",
        (tenant_id, pilot_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["config"] = json.loads(d.pop("config_json"))
    return d


def pilot_summary(store: Store, tenant_id: str, pilot_id: str) -> dict[str, Any] | None:
    """Stored pilot plus live aggregate counts from the tenant's other entities."""
    pilot = get_pilot(store, tenant_id, pilot_id)
    if pilot is None:
        return None

    def count(sql: str, params: tuple[Any, ...]) -> int:
        return store.conn.execute(sql, params).fetchone()["c"]

    summary = {
        "open_alerts": count(
            "SELECT count(*) as c FROM alert_episode WHERE tenant_id=? AND resolved_at IS NULL",
            (tenant_id,),
        ),
        "high_risk_cases": count(
            "SELECT count(*) as c FROM predictive_prediction WHERE tenant_id=? AND risk_tier='HIGH'",
            (tenant_id,),
        ),
        "active_investigations": count(
            "SELECT count(*) as c FROM investigation WHERE tenant_id=? AND status != 'closed'",
            (tenant_id,),
        ),
        "open_decisions": count(
            "SELECT count(*) as c FROM decision WHERE tenant_id=? "
            "AND status IN ('draft', 'proposed', 'accepted', 'active')",
            (tenant_id,),
        ),
        "reviews_due": count(
            "SELECT count(*) as c FROM decision WHERE tenant_id=? AND status='review_due'",
            (tenant_id,),
        ),
        "completed_reviews": count(
            "SELECT count(*) as c FROM decision WHERE tenant_id=? AND status IN ('evaluated', 'closed')",
            (tenant_id,),
        ),
        "data_readiness": "PASS" if pilot.get("dataset_revision") else "INCOMPLETE",
        "auth_security_gate": "INTERNAL_EVALUATION_ONLY",
    }
    return {"pilot": pilot, "summary": summary}


def count_pilots(store: Store, tenant_id: str) -> int:
    return store.conn.execute(
        "SELECT COUNT(*) c FROM pilot WHERE tenant_id=?",
        (tenant_id,),
    ).fetchone()["c"]


def list_pilots(
    store: Store,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        "SELECT * FROM pilot WHERE tenant_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (tenant_id, limit, offset),
    ).fetchall()
    res = []
    for r in rows:
        d = dict(r)
        d["config"] = json.loads(d.pop("config_json"))
        res.append(d)
    return res


def update_pilot_status(
    store: Store,
    tenant_id: str,
    pilot_id: str,
    target_status: PilotStatus | str,
    user_id: str,
) -> dict[str, Any]:
    pilot = get_pilot(store, tenant_id, pilot_id)
    if not pilot:
        raise LookupError(f"Pilot '{pilot_id}' not found for tenant '{tenant_id}'")

    if isinstance(target_status, str):
        target_status = PilotStatus(target_status)

    curr_status = PilotStatus(pilot["status"])
    allowed = VALID_PILOT_TRANSITIONS.get(curr_status, set())
    if target_status not in allowed:
        raise ValueError(
            f"Invalid pilot status transition from '{curr_status.value}' to '{target_status.value}'"
        )

    ts = now_iso()
    store.conn.execute(
        "UPDATE pilot SET status=?, updated_at=? WHERE tenant_id=? AND id=?",
        (target_status.value, ts, tenant_id, pilot_id),
    )
    store.conn.commit()
    return get_pilot(store, tenant_id, pilot_id)  # type: ignore[return-value]


def validate_pilot_data_readiness(
    df: pl.DataFrame,
    case_col: str = "ticket_id",
    timestamp_col: str = "timestamp",
    status_col: str = "status",
    deadline_col: str | None = "sla_deadline",
    queue_col: str | None = "queue",
) -> dict[str, Any]:
    """Quality gate validating pilot dataset readiness.
    Surfaces bad timestamps, out-of-order events, and missing required columns.
    Returns status PASS | WARNING | BLOCKED.
    """
    reasons: list[str] = []
    warnings: list[str] = []

    if df.height == 0:
        return {
            "status": "BLOCKED",
            "reasons": ["Dataset is empty (0 rows)"],
            "warnings": [],
            "metrics": {"total_rows": 0, "unique_cases": 0},
        }

    # Check case column
    actual_case_col = case_col if case_col in df.columns else ("case_id" if "case_id" in df.columns else None)
    if not actual_case_col:
        reasons.append(f"Missing required case ID column (expected '{case_col}' or 'case_id')")

    # Check timestamp column
    actual_ts_col = timestamp_col if timestamp_col in df.columns else ("created_at" if "created_at" in df.columns else None)
    if not actual_ts_col:
        reasons.append(f"Missing required timestamp column (expected '{timestamp_col}' or 'created_at')")

    # Check status/activity column
    actual_status_col = status_col if status_col in df.columns else ("activity" if "activity" in df.columns else None)
    if not actual_status_col:
        reasons.append(f"Missing required status/activity column (expected '{status_col}' or 'activity')")

    if reasons:
        return {
            "status": "BLOCKED",
            "reasons": reasons,
            "warnings": warnings,
            "metrics": {"total_rows": df.height},
        }

    # Check nulls in required columns
    null_cases = int(df[actual_case_col].is_null().sum())
    if null_cases > 0:
        reasons.append(f"Found {null_cases} rows with null case ID")

    null_ts = int(df[actual_ts_col].is_null().sum())
    if null_ts > 0:
        reasons.append(f"Found {null_ts} rows with null timestamp")

    # Check SLA deadline column
    if deadline_col and deadline_col not in df.columns and "sla_deadline" not in df.columns:
        warnings.append(f"SLA deadline column '{deadline_col}' not present; default SLA rules will apply")

    # Check Queue/Team column
    if queue_col and queue_col not in df.columns and "queue" not in df.columns and "team" not in df.columns:
        warnings.append(f"Queue/Team column '{queue_col}' not present; global queue aggregation will apply")

    # Comprehensive row and case-level quality checks
    invalid_ts_count = 0
    out_of_order_cases = 0
    completion_before_creation_cases = 0
    now_dt = datetime.now(UTC)

    if actual_case_col and actual_ts_col and actual_status_col:
        try:
            # Analyze event ordering per case
            sorted_df = df.filter(
                pl.col(actual_case_col).is_not_null() & pl.col(actual_ts_col).is_not_null()
            )
            for (cid,), sub in sorted_df.group_by(actual_case_col):
                ts_list = []
                st_list = []
                for row in sub.select([actual_ts_col, actual_status_col]).iter_rows(named=True):
                    raw_ts = str(row[actual_ts_col])
                    st_val = str(row[actual_status_col]).lower() if row[actual_status_col] else ""
                    try:
                        dt_val = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                        if dt_val.tzinfo is None:
                            dt_val = dt_val.replace(tzinfo=UTC)
                        ts_list.append(dt_val)
                        st_list.append(st_val)
                        if (dt_val - now_dt).total_seconds() > 86400 * 365:
                            warnings.append(f"Far future timestamp detected in case '{cid}': {raw_ts}")
                    except ValueError:
                        invalid_ts_count += 1

                # Check timestamp ordering
                if len(ts_list) > 1:
                    for i in range(len(ts_list) - 1):
                        if ts_list[i + 1] < ts_list[i]:
                            out_of_order_cases += 1
                            break

                # Check completion before creation
                if "created" in st_list and "completed" in st_list:
                    c_idx = st_list.index("created")
                    comp_idx = st_list.index("completed")
                    if ts_list[comp_idx] < ts_list[c_idx]:
                        completion_before_creation_cases += 1
        except Exception as e:  # noqa: BLE001 - detailed validation is best-effort; caveat is reported
            warnings.append(f"Detailed case validation caveat: {e}")

    if invalid_ts_count > 0:
        reasons.append(f"Found {invalid_ts_count} unparseable or invalid timestamp values")
    if out_of_order_cases > 0:
        reasons.append(f"Invalid event ordering detected in {out_of_order_cases} cases")
    if completion_before_creation_cases > 0:
        reasons.append(f"Completion before creation timestamp detected in {completion_before_creation_cases} cases")

    unique_cases = int(df[actual_case_col].n_unique()) if actual_case_col else 0

    status = "BLOCKED" if len(reasons) > 0 else ("WARNING" if len(warnings) > 0 else "PASS")
    return {
        "status": status,
        "reasons": reasons,
        "warnings": warnings,
        "metrics": {
            "total_rows": df.height,
            "unique_cases": unique_cases,
            "case_column": actual_case_col,
            "timestamp_column": actual_ts_col,
            "status_column": actual_status_col,
            "out_of_order_cases": out_of_order_cases,
            "completion_before_creation_cases": completion_before_creation_cases,
        },
    }


def update_pilot_config(
    store: Store,
    tenant_id: str,
    pilot_id: str,
    section: str,
    section_data: dict[str, Any],
) -> dict[str, Any]:
    """Merge a configuration section into the pilot's config_json."""
    pilot = get_pilot(store, tenant_id, pilot_id)
    if not pilot:
        raise LookupError(f"Pilot '{pilot_id}' not found for tenant '{tenant_id}'")

    config = pilot.get("config", {})
    config[section] = section_data
    ts = now_iso()

    store.conn.execute(
        "UPDATE pilot SET config_json=?, updated_at=? WHERE tenant_id=? AND id=?",
        (json.dumps(config), ts, tenant_id, pilot_id),
    )
    store.conn.commit()
    return get_pilot(store, tenant_id, pilot_id)  # type: ignore[return-value]


def analyze_workflow_mapping(
    df: pl.DataFrame,
    mapping: dict[str, str],
) -> dict[str, Any]:
    """Analyze workflow mapping against dataset and return summary stats & limitations."""
    case_col = mapping.get("case_id", "ticket_id")
    status_col = mapping.get("completion_state", "status")

    actual_case = case_col if case_col in df.columns else ("case_id" if "case_id" in df.columns else None)
    actual_status = status_col if status_col in df.columns else ("status" if "status" in df.columns else None)

    case_count = int(df[actual_case].n_unique()) if actual_case else 0
    total_events = df.height

    known_limitations: list[str] = []
    if not mapping.get("transfer") or mapping.get("transfer") not in df.columns:
        known_limitations.append("Transfer tracking not present in dataset mapping")
    if not mapping.get("reopen") or mapping.get("reopen") not in df.columns:
        known_limitations.append("Reopen indicator not mapped; reopen rate estimated from activity log")
    if mapping.get("time_basis") == "business_time":
        known_limitations.append("BUSINESS-TIME SLA NOT SUPPORTED (evaluating using UTC calendar time)")

    # Closed vs open population count
    closed_count = 0
    if actual_status and actual_status in df.columns:
        closed_matches = df.filter(
            pl.col(actual_status).cast(pl.Utf8).str.to_lowercase().is_in(["closed", "resolved", "completed", "done"])
        )
        if actual_case:
            closed_count = int(closed_matches[actual_case].n_unique())
        else:
            closed_count = closed_matches.height

    open_count = max(0, case_count - closed_count)
    event_coverage = round(min(1.0, total_events / max(1, case_count * 2)), 2)

    return {
        "case_count": case_count,
        "total_events": total_events,
        "open_population": open_count,
        "closed_population": closed_count,
        "event_coverage": event_coverage,
        "known_limitations": known_limitations,
    }
