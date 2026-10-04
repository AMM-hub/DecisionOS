"""WP-02 Classification Data & Temporal Safety Unit Tests."""

from __future__ import annotations

import polars as pl
import pytest

from decisionos_analytics.predictive import FeatureContract, RiskTargetSpec
from decisionos_analytics.risk import (
    CaseState,
    SuitabilityStatus,
    assess_risk_suitability,
    check_outcome_maturity,
    evaluate_case_state,
    extract_point_in_time_features,
)


def test_evaluate_case_state_already_overdue():
    """Verify cases at or past SLA deadline receive already_overdue state."""
    # Case past deadline
    state, reason = evaluate_case_state(
        case_id="case-101",
        observation_time_str="2026-03-01T12:00:00Z",
        deadline_str="2026-03-01T10:00:00Z",
    )
    assert state == CaseState.ALREADY_OVERDUE
    assert "SLA deadline" in reason

    # Case before deadline
    state_ok, reason_ok = evaluate_case_state(
        case_id="case-102",
        observation_time_str="2026-03-01T08:00:00Z",
        deadline_str="2026-03-01T10:00:00Z",
    )
    assert state_ok == CaseState.ELIGIBLE
    assert reason_ok is None


def test_extract_point_in_time_features_leakage_rejection():
    """Verify temporal safety engine rejects leakage trap columns and unapproved features."""
    fc_age = FeatureContract(
        feature_id="case_age_hours",
        source="workflow_events",
        event_time_semantics="event_timestamp",
        available_at_semantics="event_timestamp",
        lookback_window="24h",
        transformation_version=1,
        null_policy="zero_fill",
        eligibility_rule="active_case",
    )

    # 1. Leakage trap column present in dataframe
    leakage_df = pl.DataFrame({
        "case_id": ["case-101"],
        "timestamp": ["2026-03-01T08:00:00Z"],
        "case_age_hours": [4.0],
        "future_status": ["completed_late"],  # TRAP
    })

    with pytest.raises(ValueError) as exc:
        extract_point_in_time_features(
            events_df=leakage_df,
            observation_time_str="2026-03-01T10:00:00Z",
            approved_feature_contracts=[fc_age],
        )
    assert "leakage trap column" in str(exc.value)

    # 2. Point-in-time filtering: events after observation_time are ignored
    events_df = pl.DataFrame({
        "case_id": ["case-101", "case-101"],
        "timestamp": ["2026-03-01T08:00:00Z", "2026-03-01T12:00:00Z"],
        "case_age_hours": [4.0, 8.0],
    })
    res = extract_point_in_time_features(
        events_df=events_df,
        observation_time_str="2026-03-01T10:00:00Z",  # Cutoff at 10:00
        approved_feature_contracts=[fc_age],
    )
    # Event at 12:00 was post-cutoff; latest value before 10:00 was 4.0
    assert res["case_age_hours"] == 4.0


def test_check_outcome_maturity():
    """Verify un-matured cases without positive outcome are identified as un-matured."""
    obs_time = "2026-03-01T00:00:00Z"
    window = "7d"
    
    # 1. Current time = 3 days after obs_time, no positive outcome yet -> UNMATURED
    is_matured, reason = check_outcome_maturity(
        observation_time_str=obs_time,
        outcome_window_str=window,
        current_time_str="2026-03-04T00:00:00Z",
        outcome_occurred=False,
    )
    assert is_matured is False
    assert "not yet matured" in reason

    # 2. Current time = 8 days after obs_time, no positive outcome -> MATURED (confirmed negative)
    is_matured_neg, _ = check_outcome_maturity(
        observation_time_str=obs_time,
        outcome_window_str=window,
        current_time_str="2026-03-09T00:00:00Z",
        outcome_occurred=False,
    )
    assert is_matured_neg is True

    # 3. Positive outcome occurred on day 2 -> MATURED positive
    is_matured_pos, _ = check_outcome_maturity(
        observation_time_str=obs_time,
        outcome_window_str=window,
        current_time_str="2026-03-04T00:00:00Z",
        outcome_occurred=True,
        outcome_occurred_at_str="2026-03-03T00:00:00Z",
    )
    assert is_matured_pos is True


def test_assess_risk_suitability_policy():
    """Verify suitability assessment evaluates configurable target policy, not hardcoded defaults."""
    target_spec = RiskTargetSpec(
        target_id="tgt-test",
        tenant_id="tenant_alpha",
        name="Case SLA Breach 24h",
        entity_type="workflow_case",
        outcome_definition={"metric": "duration", "operator": "gt", "value": 24.0},
        outcome_window="24h",
        deadline_semantics="relative_24h",
    )

    # 1. Empty dataset
    empty_df = pl.DataFrame({"label": pl.Series([], dtype=pl.Int64)})
    s_empty = assess_risk_suitability(empty_df, target_spec)
    assert s_empty["suitable"] is False
    assert s_empty["status"] == SuitabilityStatus.INSUFFICIENT_HISTORY.value

    # 2. Dataset with positive events below policy minimum
    low_pos_df = pl.DataFrame({"label": [0]*20 + [1]*1})  # 1 positive event
    policy = {"min_sample_size": 10, "min_positive_events": 5, "max_imbalance_ratio": 100.0}
    s_low = assess_risk_suitability(low_pos_df, target_spec, policy_config=policy)
    assert s_low["suitable"] is False
    assert s_low["status"] == SuitabilityStatus.INSUFFICIENT_EVENTS.value

    # 3. Suitable dataset meeting policy
    good_df = pl.DataFrame({"label": [0]*15 + [1]*5})
    s_good = assess_risk_suitability(good_df, target_spec, policy_config=policy)
    assert s_good["suitable"] is True
    assert s_good["status"] == SuitabilityStatus.SUITABLE.value
