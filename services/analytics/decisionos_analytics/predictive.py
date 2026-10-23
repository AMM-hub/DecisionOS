"""WP-00 Predictive Contracts & Model Registry.

Implements:
1. RiskTargetSpec: typed predictive target definition.
2. FeatureContract: feature source, event time semantics, null policy, and eligibility.
3. ModelLifecycle: draft -> evaluated -> approved -> active -> degraded -> suspended -> retired.
4. Model Registry CRUD, validation, and historical immutability.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .store import Store, new_id, now_iso


class ModelStatus(str, Enum):
    DRAFT = "draft"
    EVALUATED = "evaluated"
    APPROVED = "approved"
    ACTIVE = "active"
    DEGRADED = "degraded"
    SUSPENDED = "suspended"
    RETIRED = "retired"


# Valid state machine transitions for predictive models
VALID_MODEL_TRANSITIONS: dict[ModelStatus, set[ModelStatus]] = {
    ModelStatus.DRAFT: {ModelStatus.EVALUATED, ModelStatus.RETIRED},
    ModelStatus.EVALUATED: {ModelStatus.APPROVED, ModelStatus.RETIRED},
    ModelStatus.APPROVED: {ModelStatus.ACTIVE, ModelStatus.RETIRED},
    ModelStatus.ACTIVE: {ModelStatus.DEGRADED, ModelStatus.SUSPENDED, ModelStatus.RETIRED},
    ModelStatus.DEGRADED: {ModelStatus.ACTIVE, ModelStatus.SUSPENDED, ModelStatus.RETIRED},
    ModelStatus.SUSPENDED: {ModelStatus.ACTIVE, ModelStatus.RETIRED},
    ModelStatus.RETIRED: set(),
}


@dataclass
class RiskTargetSpec:
    target_id: str
    tenant_id: str
    name: str
    entity_type: str  # e.g., 'workflow_case'
    outcome_definition: dict[str, Any]  # e.g., {'metric': 'duration_hours', 'condition': 'gt', 'threshold': 24.0}
    observation_time_semantics: str = "as_of"
    outcome_window: str = "24h"
    eligible_population: str = "all"
    deadline_semantics: str = "fixed_sla"
    time_basis: str = "calendar_utc"  # business_time is unsupported

    def to_dict(self) -> dict[str, Any]:
        if self.time_basis != "calendar_utc":
            raise ValueError(f"Time basis '{self.time_basis}' is unsupported. Only 'calendar_utc' is supported.")
        return {
            "target_id": self.target_id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "entity_type": self.entity_type,
            "outcome_definition": self.outcome_definition,
            "observation_time_semantics": self.observation_time_semantics,
            "outcome_window": self.outcome_window,
            "eligible_population": self.eligible_population,
            "deadline_semantics": self.deadline_semantics,
            "time_basis": self.time_basis,
        }


@dataclass
class FeatureContract:
    feature_id: str
    source: str = "workflow_events"
    event_time_semantics: str = "event_timestamp"
    available_at_semantics: str = "event_timestamp"
    lookback_window: str = "24h"
    transformation_version: int = 1
    null_policy: str = "impute_zero"
    eligibility_rule: str = "all"

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "source": self.source,
            "event_time_semantics": self.event_time_semantics,
            "available_at_semantics": self.available_at_semantics,
            "lookback_window": self.lookback_window,
            "transformation_version": self.transformation_version,
            "null_policy": self.null_policy,
            "eligibility_rule": self.eligibility_rule,
        }


def create_predictive_target(
    store: Store,
    tenant_id: str,
    name: str,
    entity_type: str,
    outcome_definition: dict[str, Any],
    outcome_window: str,
    deadline_semantics: str,
    user_id: str,
    time_basis: str = "calendar_utc",
) -> dict[str, Any]:
    if time_basis != "calendar_utc":
        raise ValueError(f"Unsupported time_basis '{time_basis}'. Only 'calendar_utc' is supported.")
    target_id = f"tgt-{new_id()[:12]}"
    ts = now_iso()

    store.conn.execute(
        """INSERT INTO predictive_target (
            tenant_id, id, name, entity_type, outcome_definition_json,
            observation_time_semantics, outcome_window, eligible_population,
            deadline_semantics, time_basis, created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, 'as_of', ?, 'all', ?, ?, ?, ?)""",
        (
            tenant_id,
            target_id,
            name,
            entity_type,
            json.dumps(outcome_definition),
            outcome_window,
            deadline_semantics,
            time_basis,
            user_id,
            ts,
        ),
    )
    store.conn.commit()

    return {
        "id": target_id,
        "target_id": target_id,
        "tenant_id": tenant_id,
        "name": name,
        "entity_type": entity_type,
        "outcome_definition": outcome_definition,
        "outcome_window": outcome_window,
        "deadline_semantics": deadline_semantics,
        "time_basis": time_basis,
        "created_by": user_id,
        "created_at": ts,
    }


def get_predictive_target(store: Store, tenant_id: str, target_id: str) -> dict[str, Any] | None:
    row = store.conn.execute(
        "SELECT * FROM predictive_target WHERE tenant_id=? AND id=?",
        (tenant_id, target_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["outcome_definition"] = json.loads(d.pop("outcome_definition_json"))
    return d


def count_predictive_targets(store: Store, tenant_id: str) -> int:
    return store.conn.execute(
        "SELECT COUNT(*) c FROM predictive_target WHERE tenant_id=?",
        (tenant_id,),
    ).fetchone()["c"]


def list_predictive_targets(
    store: Store,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        "SELECT * FROM predictive_target WHERE tenant_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (tenant_id, limit, offset),
    ).fetchall()
    res = []
    for r in rows:
        d = dict(r)
        d["outcome_definition"] = json.loads(d.pop("outcome_definition_json"))
        res.append(d)
    return res


def register_predictive_model(
    store: Store,
    tenant_id: str,
    target_id: str,
    algorithm: str,
    feature_contracts: Sequence[FeatureContract | dict[str, Any]] | None = None,
    training_dataset_revision: int = 1,
    training_time_range: dict[str, str] | None = None,
    evaluation_time_range: dict[str, str] | None = None,
    hyperparameters: dict[str, Any] | None = None,
    calibration_method: str = "platt",
    threshold_policy: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    checksum: str = "",
    user_id: str = "system",
    intended_use: str = "",
    excluded_uses: str = "",
    model_kind: str = "classification_risk",
    feature_contract_specs: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    target = get_predictive_target(store, tenant_id, target_id)
    if not target:
        raise LookupError(f"Predictive target '{target_id}' not found for tenant '{tenant_id}'")

    model_id = f"mdl-{new_id()[:12]}"
    ts = now_iso()

    specs = feature_contract_specs or feature_contracts or []
    fcs: list[FeatureContract] = []
    for fc in specs:
        if isinstance(fc, dict):
            fcs.append(FeatureContract(**fc))
        elif isinstance(fc, FeatureContract):
            fcs.append(fc)

    fc_json = json.dumps([fc.to_dict() for fc in fcs])

    if not checksum:
        checksum = hashlib.sha256(f"{tenant_id}:{target_id}:{algorithm}:{ts}".encode()).hexdigest()

    training_time_range = training_time_range or {"start": "2026-01-01T00:00:00Z", "end": "2026-02-01T00:00:00Z"}
    evaluation_time_range = evaluation_time_range or {"start": "2026-02-01T00:00:00Z", "end": "2026-02-15T00:00:00Z"}
    hyperparameters = hyperparameters or {}
    threshold_policy = threshold_policy or {"policy_type": "capacity", "capacity": 20}
    metrics = metrics or {}

    store.conn.execute(
        """INSERT INTO predictive_model (
            tenant_id, id, target_id, version, model_kind, algorithm,
            feature_contract_json, training_dataset_revision, training_time_range_json,
            evaluation_time_range_json, hyperparameters_json, calibration_method,
            threshold_policy_json, metrics_json, checksum, status, intended_use,
            excluded_uses, created_by, created_at
        ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)""",
        (
            tenant_id,
            model_id,
            target_id,
            model_kind,
            algorithm,
            fc_json,
            training_dataset_revision,
            json.dumps(training_time_range),
            json.dumps(evaluation_time_range),
            json.dumps(hyperparameters),
            calibration_method,
            json.dumps(threshold_policy),
            json.dumps(metrics),
            checksum,
            intended_use,
            excluded_uses,
            user_id,
            ts,
        ),
    )
    store.conn.commit()

    return get_predictive_model(store, tenant_id, model_id)  # type: ignore[return-value]


def get_predictive_model(store: Store, tenant_id: str, model_id: str) -> dict[str, Any] | None:
    row = store.conn.execute(
        "SELECT * FROM predictive_model WHERE tenant_id=? AND id=?",
        (tenant_id, model_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["feature_contract"] = json.loads(d.pop("feature_contract_json"))
    d["training_time_range"] = json.loads(d.pop("training_time_range_json"))
    d["evaluation_time_range"] = json.loads(d.pop("evaluation_time_range_json"))
    d["hyperparameters"] = json.loads(d.pop("hyperparameters_json"))
    d["threshold_policy"] = json.loads(d.pop("threshold_policy_json"))
    d["metrics"] = json.loads(d.pop("metrics_json"))
    return d


def count_predictive_models(store: Store, tenant_id: str) -> int:
    return store.conn.execute(
        "SELECT COUNT(*) c FROM predictive_model WHERE tenant_id=?",
        (tenant_id,),
    ).fetchone()["c"]


def list_predictive_models(
    store: Store,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        "SELECT * FROM predictive_model WHERE tenant_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (tenant_id, limit, offset),
    ).fetchall()
    res = []
    for r in rows:
        d = dict(r)
        d["feature_contract"] = json.loads(d.pop("feature_contract_json"))
        d["training_time_range"] = json.loads(d.pop("training_time_range_json"))
        d["evaluation_time_range"] = json.loads(d.pop("evaluation_time_range_json"))
        d["hyperparameters"] = json.loads(d.pop("hyperparameters_json"))
        d["threshold_policy"] = json.loads(d.pop("threshold_policy_json"))
        d["metrics"] = json.loads(d.pop("metrics_json"))
        res.append(d)
    return res


def transition_model_status(
    store: Store,
    tenant_id: str,
    model_id: str,
    target_status: ModelStatus | str,
    user_id: str,
) -> dict[str, Any]:
    mdl = get_predictive_model(store, tenant_id, model_id)
    if not mdl:
        raise LookupError(f"Model '{model_id}' not found")

    if isinstance(target_status, str):
        target_status = ModelStatus(target_status)

    current_status = ModelStatus(mdl["status"])
    allowed = VALID_MODEL_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise ValueError(
            f"Invalid model status transition from '{current_status.value}' to '{target_status.value}'"
        )

    ts = now_iso()
    updates = ["status = ?", "updated_at = ?"] if "updated_at" in mdl else ["status = ?"]
    params: list[Any] = [target_status.value]

    if target_status == ModelStatus.APPROVED:
        updates.append("approved_by = ?")
        updates.append("approved_at = ?")
        params.extend([user_id, ts])
    elif target_status == ModelStatus.ACTIVE:
        updates.append("activated_at = ?")
        params.append(ts)

    params.extend([tenant_id, model_id])
    query = f"UPDATE predictive_model SET {', '.join(updates)} WHERE tenant_id=? AND id=?"
    store.conn.execute(query, params)
    store.conn.commit()

    return get_predictive_model(store, tenant_id, model_id)  # type: ignore[return-value]


def record_prediction(
    store: Store,
    tenant_id: str,
    model_id: str,
    target_id: str,
    entity_id: str,
    observation_time: str,
    score: float,
    risk_tier: str,
    threshold_used: float,
    outcome_window: str,
    source_dataset_revision: int,
    feature_snapshot: dict[str, Any],
    suitability_status: str = "suitable",
) -> dict[str, Any]:
    mdl = get_predictive_model(store, tenant_id, model_id)
    if not mdl:
        raise LookupError(f"Model '{model_id}' not found")
    if mdl["status"] == ModelStatus.SUSPENDED.value:
        raise ValueError(f"Cannot generate prediction: model '{model_id}' is SUSPENDED")

    pred_id = f"prd-{new_id()[:12]}"
    ts = now_iso()

    store.conn.execute(
        """INSERT INTO predictive_prediction (
            tenant_id, id, model_id, model_version, target_id, entity_id,
            observation_time, score, risk_tier, threshold_used, outcome_window,
            source_dataset_revision, feature_snapshot_json, suitability_status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tenant_id,
            pred_id,
            model_id,
            mdl["version"],
            target_id,
            entity_id,
            observation_time,
            score,
            risk_tier,
            threshold_used,
            outcome_window,
            source_dataset_revision,
            json.dumps(feature_snapshot),
            suitability_status,
            ts,
        ),
    )
    store.conn.commit()

    return {
        "id": pred_id,
        "prediction_id": pred_id,
        "tenant_id": tenant_id,
        "model_id": model_id,
        "model_version": mdl["version"],
        "target_id": target_id,
        "entity_id": entity_id,
        "observation_time": observation_time,
        "score": score,
        "risk_tier": risk_tier,
        "threshold": threshold_used,
        "threshold_used": threshold_used,
        "outcome_window": outcome_window,
        "dataset_revision": source_dataset_revision,
        "source_dataset_revision": source_dataset_revision,
        "feature_snapshot": feature_snapshot,
        "suitability_status": suitability_status,
        "created_at": ts,
    }


def get_prediction(store: Store, tenant_id: str, prediction_id: str) -> dict[str, Any] | None:
    row = store.conn.execute(
        "SELECT * FROM predictive_prediction WHERE tenant_id=? AND id=?",
        (tenant_id, prediction_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["feature_snapshot"] = json.loads(d.pop("feature_snapshot_json"))
    d["dataset_revision"] = d.get("source_dataset_revision", 1)
    d["threshold"] = d.get("threshold_used", 0.5)
    return d
