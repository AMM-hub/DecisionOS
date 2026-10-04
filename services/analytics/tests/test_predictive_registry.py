"""WP-00 Predictive Contracts & Model Registry Tests.

Verifies:
1. Target creation & validation.
2. Feature contract construction & serialization.
3. Model lifecycle state machine enforcement (draft -> evaluated -> approved -> active -> suspended/retired).
4. Prediction recording & historical immutability.
5. Cross-tenant isolation.
"""

from __future__ import annotations

import pytest
from decisionos_analytics.store import Store
from decisionos_analytics.predictive import (
    FeatureContract,
    ModelStatus,
    RiskTargetSpec,
    create_predictive_target,
    get_predictive_model,
    get_predictive_target,
    get_prediction,
    record_prediction,
    register_predictive_model,
    transition_model_status,
)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test_predictive.db")


def test_target_spec_validation_and_creation(store):
    tenant_id = "tenant_alpha"
    user_id = "alpha.manager"

    # 1. Invalid time basis raises ValueError
    with pytest.raises(ValueError, match="unsupported"):
        spec = RiskTargetSpec(
            target_id="tgt-1",
            tenant_id=tenant_id,
            name="SLA Breach",
            entity_type="workflow_case",
            outcome_definition={"threshold": 24},
            time_basis="business_time",
        )
        spec.to_dict()

    # 2. Valid target creation
    tgt = create_predictive_target(
        store=store,
        tenant_id=tenant_id,
        name="Case SLA Breach 24h",
        entity_type="workflow_case",
        outcome_definition={"metric": "duration", "operator": "gt", "value": 24.0},
        outcome_window="24h",
        deadline_semantics="relative_start_24h",
        user_id=user_id,
    )
    assert tgt["target_id"].startswith("tgt-")
    assert tgt["time_basis"] == "calendar_utc"

    fetched = get_predictive_target(store, tenant_id, tgt["target_id"])
    assert fetched is not None
    assert fetched["name"] == "Case SLA Breach 24h"


def test_model_lifecycle_state_machine(store):
    tenant_id = "tenant_alpha"
    user_id = "alpha.manager"

    # Create target & feature contracts
    tgt = create_predictive_target(
        store, tenant_id, "Target 1", "workflow_case", {"value": 1}, "24h", "fixed", user_id
    )
    fc = FeatureContract(
        feature_id="case_age_hours",
        source="workflow.event_log",
        event_time_semantics="event_timestamp",
        available_at_semantics="as_of",
        lookback_window="30d",
    )

    # Register model in DRAFT
    mdl = register_predictive_model(
        store=store,
        tenant_id=tenant_id,
        target_id=tgt["target_id"],
        algorithm="LogisticRegression",
        feature_contracts=[fc],
        training_dataset_revision=1,
        training_time_range={"start": "2024-01-01T00:00:00Z", "end": "2024-06-01T00:00:00Z"},
        evaluation_time_range={"start": "2024-06-01T00:00:00Z", "end": "2024-07-01T00:00:00Z"},
        hyperparameters={"C": 1.0},
        calibration_method="platt",
        threshold_policy={"capacity_k": 10, "operating_threshold": 0.45},
        metrics={"brier_score": 0.12, "pr_auc": 0.82},
        checksum="sha256-abc123mock",
        user_id=user_id,
    )
    assert mdl["status"] == "draft"

    # 1. Invalid transition DRAFT -> ACTIVE raises ValueError
    with pytest.raises(ValueError, match="Invalid model status transition"):
        transition_model_status(store, tenant_id, mdl["id"], ModelStatus.ACTIVE, user_id)

    # 2. Valid transition sequence: DRAFT -> EVALUATED -> APPROVED -> ACTIVE
    m1 = transition_model_status(store, tenant_id, mdl["id"], ModelStatus.EVALUATED, user_id)
    assert m1["status"] == "evaluated"

    m2 = transition_model_status(store, tenant_id, mdl["id"], ModelStatus.APPROVED, user_id)
    assert m2["status"] == "approved"
    assert m2["approved_by"] == user_id

    m3 = transition_model_status(store, tenant_id, mdl["id"], ModelStatus.ACTIVE, user_id)
    assert m3["status"] == "active"
    assert m3["activated_at"] is not None

    # 3. Transition ACTIVE -> SUSPENDED
    m4 = transition_model_status(store, tenant_id, mdl["id"], ModelStatus.SUSPENDED, user_id)
    assert m4["status"] == "suspended"

    # 4. SUSPENDED model cannot generate predictions
    with pytest.raises(ValueError, match="SUSPENDED"):
        record_prediction(
            store=store,
            tenant_id=tenant_id,
            model_id=mdl["id"],
            target_id=tgt["target_id"],
            entity_id="case-101",
            observation_time="2024-07-01T12:00:00Z",
            score=0.78,
            risk_tier="high",
            threshold_used=0.45,
            outcome_window="24h",
            source_dataset_revision=1,
            feature_snapshot={"case_age_hours": 18.5},
        )


def test_prediction_immutability_and_isolation(store):
    tenant_alpha = "tenant_alpha"
    tenant_beta = "tenant_beta"
    user_id = "alpha.manager"

    tgt = create_predictive_target(
        store, tenant_alpha, "Target Alpha", "workflow_case", {"v": 1}, "24h", "fixed", user_id
    )
    fc = FeatureContract("f1", "src", "ts", "as_of", "30d")
    mdl = register_predictive_model(
        store, tenant_alpha, tgt["target_id"], "LogisticRegression", [fc], 1,
        {"start": "2024-01-01T00:00:00Z", "end": "2024-06-01T00:00:00Z"},
        {"start": "2024-06-01T00:00:00Z", "end": "2024-07-01T00:00:00Z"},
        {}, "platt", {}, {"brier_score": 0.1}, "chk1", user_id
    )
    transition_model_status(store, tenant_alpha, mdl["id"], ModelStatus.EVALUATED, user_id)
    transition_model_status(store, tenant_alpha, mdl["id"], ModelStatus.APPROVED, user_id)
    transition_model_status(store, tenant_alpha, mdl["id"], ModelStatus.ACTIVE, user_id)

    # Record prediction
    pred = record_prediction(
        store=store,
        tenant_id=tenant_alpha,
        model_id=mdl["id"],
        target_id=tgt["target_id"],
        entity_id="case-999",
        observation_time="2024-07-02T10:00:00Z",
        score=0.64,
        risk_tier="medium",
        threshold_used=0.50,
        outcome_window="24h",
        source_dataset_revision=1,
        feature_snapshot={"f1": 10},
    )
    assert pred["prediction_id"].startswith("prd-")

    # Verify retrieval
    p_fetched = get_prediction(store, tenant_alpha, pred["prediction_id"])
    assert p_fetched is not None
    assert p_fetched["score"] == 0.64
    assert p_fetched["feature_snapshot"] == {"f1": 10}

    # Cross-tenant isolation check: Tenant Beta cannot access Tenant Alpha prediction or model
    assert get_prediction(store, tenant_beta, pred["prediction_id"]) is None
    assert get_predictive_model(store, tenant_beta, mdl["id"]) is None
