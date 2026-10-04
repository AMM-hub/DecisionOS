"""D3-A Case-Level Classification Risk & Temporal Safety Engine.

Enforces temporal correctness (available_at <= observation_time), outcome maturity,
already-overdue case state handling, leakage feature rejection, and configurable suitability assessment.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import polars as pl

from .predictive import FeatureContract, RiskTargetSpec


class CaseState(str, Enum):
    ELIGIBLE = "eligible"
    ALREADY_OVERDUE = "already_overdue"
    EXCLUDED = "excluded"
    UNMATURED = "unmatured"
    PREDICTION_UNAVAILABLE = "prediction_unavailable"


class SuitabilityStatus(str, Enum):
    SUITABLE = "suitable"
    LIMITED = "limited"
    INSUFFICIENT_HISTORY = "insufficient_history"
    INSUFFICIENT_EVENTS = "insufficient_events"
    SEVERE_CLASS_IMBALANCE = "severe_class_imbalance"
    INVALID_TARGET = "invalid_target"
    DATA_QUALITY_BLOCKED = "data_quality_blocked"
    VALIDATION_NOT_FEASIBLE = "validation_not_feasible"


# Standard known leakage trap columns to explicitly reject if encountered without temporal proof
DEFAULT_LEAKAGE_TRAPS = {
    "future_status",
    "completion_time_future",
    "final_resolution",
    "post_observation_event_count",
    "resolution_time",
    "final_outcome",
}


def parse_datetime(dt_str: str) -> datetime:
    """Parse ISO datetime string into UTC datetime."""
    dt_str = dt_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_duration_to_seconds(duration_str: str) -> float:
    """Parse duration strings like '24h', '7d', '60m', '3600s' to seconds."""
    s = duration_str.strip().lower()
    if s.endswith("d"):
        return float(s[:-1]) * 86400.0
    if s.endswith("h"):
        return float(s[:-1]) * 3600.0
    if s.endswith("m"):
        return float(s[:-1]) * 60.0
    if s.endswith("s"):
        return float(s[:-1])
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"Unrecognized duration format: {duration_str}")


def evaluate_case_state(
    case_id: str,
    observation_time_str: str,
    deadline_str: str | None,
    current_status: str | None = None,
    excluded_statuses: list[str] | None = None,
) -> tuple[CaseState, str | None]:
    """Evaluate whether a case is eligible for speculative future risk scoring,
    or is already_overdue or excluded.
    """
    excluded_statuses = excluded_statuses or ["cancelled", "archived", "completed"]
    if current_status and current_status in excluded_statuses:
        return CaseState.EXCLUDED, f"Case status '{current_status}' is excluded"

    if deadline_str:
        obs_dt = parse_datetime(observation_time_str)
        deadline_dt = parse_datetime(deadline_str)
        if obs_dt >= deadline_dt:
            return CaseState.ALREADY_OVERDUE, f"Observation time {observation_time_str} >= SLA deadline {deadline_str}"

    return CaseState.ELIGIBLE, None


def extract_point_in_time_features(
    events_df: pl.DataFrame,
    observation_time_str: str,
    approved_feature_contracts: list[FeatureContract],
    trap_columns: set[str] | None = None,
) -> dict[str, Any]:
    """Extract case features strictly using events available at or before observation_time (t_obs).
    Rejects non-approved features and known leakage trap columns.
    """
    trap_columns = trap_columns or DEFAULT_LEAKAGE_TRAPS
    obs_dt = parse_datetime(observation_time_str)

    approved_feature_ids = {f.feature_id for f in approved_feature_contracts}

    # Verify no unapproved or leakage trap columns exist in input dataframe
    for col in events_df.columns:
        if col in trap_columns:
            raise ValueError(f"Temporal leakage trap column '{col}' detected and rejected by temporal safety engine.")
        if col not in ("case_id", "timestamp") and col not in approved_feature_ids:
            raise ValueError(f"Feature column '{col}' is not in approved feature contracts.")

    # Filter events to those occurred on or before observation_time
    filtered_df = events_df
    if "timestamp" in events_df.columns:
        parsed_ts = [parse_datetime(ts_val) for ts_val in events_df["timestamp"].to_list()]
        filtered_df = events_df.with_columns(
            pl.Series("_ts", parsed_ts)
        ).filter(pl.col("_ts") <= obs_dt)

    features: dict[str, Any] = {}
    for fc in approved_feature_contracts:
        fid = fc.feature_id
        if fid in filtered_df.columns:
            val = filtered_df[fid].tail(1).item() if filtered_df.height > 0 else None
            features[fid] = val
        else:
            features[fid] = None

    return features


def check_outcome_maturity(
    observation_time_str: str,
    outcome_window_str: str,
    current_time_str: str,
    outcome_occurred: bool,
    outcome_occurred_at_str: str | None = None,
) -> tuple[bool, str | None]:
    """Determine whether a case observation outcome has matured.
    An un-matured observation without a positive outcome cannot be treated as a confirmed negative.
    """
    obs_dt = parse_datetime(observation_time_str)
    window_sec = parse_duration_to_seconds(outcome_window_str)
    maturity_deadline_dt = obs_dt + timedelta(seconds=window_sec)

    curr_dt = parse_datetime(current_time_str)

    if outcome_occurred:
        if outcome_occurred_at_str:
            occurred_dt = parse_datetime(outcome_occurred_at_str)
            if occurred_dt <= maturity_deadline_dt:
                return True, "Positive outcome observed within window"
            else:
                return True, "Negative outcome (positive occurred post-window)"
        return True, "Positive outcome observed"

    if curr_dt >= maturity_deadline_dt:
        return True, "Negative outcome confirmed after full outcome window"
    else:
        return False, f"Outcome window ({outcome_window_str}) not yet matured as of {current_time_str}"


def assess_risk_suitability(
    dataset: pl.DataFrame,
    target_spec: RiskTargetSpec,
    policy_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Target-specific assessment of dataset suitability.
    Avoids universal N < 30 / Brier > 0.20 hardcoded assumptions.
    """
    policy = policy_config or {
        "min_sample_size": 10,
        "min_positive_events": 3,
        "min_prevalence": 0.01,
        "max_imbalance_ratio": 100.0,
    }

    n_samples = dataset.height
    reasons: list[str] = []

    if n_samples == 0:
        return {
            "status": SuitabilityStatus.INSUFFICIENT_HISTORY.value,
            "suitable": False,
            "reason": "Dataset is empty",
            "metrics": {"n_samples": 0, "n_positive": 0, "prevalence": 0.0},
        }

    min_n = policy.get("min_sample_size", 10)
    if n_samples < min_n:
        reasons.append(f"Sample count ({n_samples}) below target policy minimum ({min_n})")

    label_col = "label" if "label" in dataset.columns else "outcome"
    if label_col not in dataset.columns:
        return {
            "status": SuitabilityStatus.INVALID_TARGET.value,
            "suitable": False,
            "reason": f"Target column '{label_col}' missing from dataset",
            "metrics": {"n_samples": n_samples},
        }

    pos_count = int(dataset.filter(pl.col(label_col) == 1).height)
    min_pos = policy.get("min_positive_events", 3)
    if pos_count < min_pos:
        reasons.append(f"Positive event count ({pos_count}) below target policy minimum ({min_pos})")

    prevalence = float(pos_count / n_samples) if n_samples > 0 else 0.0
    min_prev = policy.get("min_prevalence", 0.01)
    if prevalence < min_prev and pos_count > 0:
        reasons.append(f"Prevalence ({prevalence:.4f}) below policy minimum ({min_prev})")

    neg_count = n_samples - pos_count
    imbalance_ratio = (neg_count / pos_count) if pos_count > 0 else float("inf")
    max_imb = policy.get("max_imbalance_ratio", 100.0)
    if imbalance_ratio > max_imb:
        reasons.append(f"Severe class imbalance ratio ({imbalance_ratio:.1f}:1) exceeds policy limit ({max_imb}:1)")

    if pos_count < min_pos:
        status = SuitabilityStatus.INSUFFICIENT_EVENTS.value
        suitable = False
    elif n_samples < min_n:
        status = SuitabilityStatus.INSUFFICIENT_HISTORY.value
        suitable = False
    elif imbalance_ratio > max_imb:
        status = SuitabilityStatus.SEVERE_CLASS_IMBALANCE.value
        suitable = False
    elif len(reasons) > 0:
        status = SuitabilityStatus.LIMITED.value
        suitable = True
    else:
        status = SuitabilityStatus.SUITABLE.value
        suitable = True

    return {
        "status": status,
        "suitable": suitable,
        "reasons": reasons,
        "metrics": {
            "n_samples": n_samples,
            "n_positive": pos_count,
            "n_negative": neg_count,
            "prevalence": round(prevalence, 4),
            "imbalance_ratio": round(imbalance_ratio, 2) if math.isfinite(imbalance_ratio) else None,
        },
    }
