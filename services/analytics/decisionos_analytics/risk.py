"""D3-A Case-Level Classification Risk & Temporal Safety Engine.

Enforces temporal correctness (available_at <= observation_time), outcome maturity,
already-overdue case state handling, leakage feature rejection, and configurable suitability assessment.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

import numpy as np
import polars as pl
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, confusion_matrix, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

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
        dt = dt.replace(tzinfo=UTC)
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


# ---------------------------------------------------------------------------
# Classification Models
# ---------------------------------------------------------------------------

class BaseRateClassifier:
    """Baseline classifier predicting constant training set positive prevalence."""

    def __init__(self) -> None:
        self.base_rate: float = 0.5
        self.classes_: np.ndarray = np.array([0, 1])

    def fit(self, X: np.ndarray, y: np.ndarray) -> BaseRateClassifier:
        if len(y) > 0:
            self.base_rate = float(np.mean(y))
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        n = len(X)
        probs = np.zeros((n, 2))
        probs[:, 1] = self.base_rate
        probs[:, 0] = 1.0 - self.base_rate
        return probs


class LogisticRegressionClassifier:
    """Logistic regression classifier with scaler fit on training data."""

    def __init__(self) -> None:
        self.scaler = StandardScaler()
        self.model = LogisticRegression(solver="lbfgs", max_iter=1000, random_state=42)

    def fit(self, X: np.ndarray, y: np.ndarray) -> LogisticRegressionClassifier:
        if len(X) > 0:
            X_scaled = self.scaler.fit_transform(X)
            self.model.fit(X_scaled, y)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if len(X) == 0:
            return np.zeros((0, 2))
        X_scaled = self.scaler.transform(X)
        return self.model.predict_proba(X_scaled)


class RandomForestChallengerClassifier:
    """RandomForest challenger model."""

    def __init__(self) -> None:
        self.model = RandomForestClassifier(n_estimators=50, max_depth=4, random_state=42)

    def fit(self, X: np.ndarray, y: np.ndarray) -> RandomForestChallengerClassifier:
        if len(X) > 0:
            self.model.fit(X, y)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if len(X) == 0:
            return np.zeros((0, 2))
        return self.model.predict_proba(X)


# ---------------------------------------------------------------------------
# Calibration & Metrics
# ---------------------------------------------------------------------------

class PlattCalibrator:
    """Platt / Sigmoid scaling probability calibrator.
    Uses separate validation dataset not used during model fitting.
    If sample size is insufficient, abstains from claiming calibrated probabilities.
    """

    def __init__(self, min_calib_samples: int = 10, min_pos_events: int = 2) -> None:
        self.min_calib_samples = min_calib_samples
        self.min_pos_events = min_pos_events
        self.calibrator: LogisticRegression | None = None
        self.is_calibrated: bool = False
        self.probability_status: str = "uncalibrated"

    def fit(self, raw_probs: np.ndarray, y_val: np.ndarray) -> PlattCalibrator:
        n_samples = len(y_val)
        n_pos = int(np.sum(y_val))

        if n_samples < self.min_calib_samples or n_pos < self.min_pos_events or n_pos == n_samples:
            self.is_calibrated = False
            self.probability_status = "uncalibrated"
            self.calibrator = None
            return self

        eps = 1e-7
        clipped = np.clip(raw_probs, eps, 1.0 - eps)
        logit_scores = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)

        lr = LogisticRegression(solver="lbfgs", C=1.0)
        lr.fit(logit_scores, y_val)
        self.calibrator = lr
        self.is_calibrated = True
        self.probability_status = "calibrated"
        return self

    def transform(self, raw_probs: np.ndarray) -> np.ndarray:
        if not self.is_calibrated or self.calibrator is None:
            return raw_probs

        eps = 1e-7
        clipped = np.clip(raw_probs, eps, 1.0 - eps)
        logit_scores = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)
        return self.calibrator.predict_proba(logit_scores)[:, 1]


def calculate_classification_metrics(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Calculate comprehensive classification metrics."""
    n_samples = len(y_true)
    if n_samples == 0:
        return {"sample_count": 0}

    pos_events = int(np.sum(y_true))
    prevalence = float(np.mean(y_true))

    brier = float(brier_score_loss(y_true, y_prob)) if n_samples > 0 else None

    roc_auc = None
    pr_auc = None
    log_l = None

    if 0 < pos_events < n_samples:
        try:
            roc_auc = float(roc_auc_score(y_true, y_prob))
        except ValueError:
            roc_auc = None
        try:
            pr_auc = float(average_precision_score(y_true, y_prob))
        except ValueError:
            pr_auc = None
        try:
            log_l = float(log_loss(y_true, np.clip(y_prob, 1e-7, 1 - 1e-7)))
        except ValueError:
            log_l = None

    y_pred = (y_prob >= threshold).astype(int)
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()

    precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0

    return {
        "sample_count": n_samples,
        "positive_event_count": pos_events,
        "prevalence": round(prevalence, 4),
        "brier_score": round(brier, 6) if brier is not None else None,
        "roc_auc": round(roc_auc, 6) if roc_auc is not None else None,
        "pr_auc": round(pr_auc, 6) if pr_auc is not None else None,
        "log_loss": round(log_l, 6) if log_l is not None else None,
        "threshold": round(threshold, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


# ---------------------------------------------------------------------------
# Threshold Policy & Candidate Promotion
# ---------------------------------------------------------------------------

def determine_operating_threshold(
    y_prob: np.ndarray,
    y_true: np.ndarray | None = None,
    policy_type: str = "capacity",
    policy_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Determine operating threshold based on capacity (top K), precision target, recall target, or fixed."""
    policy_params = policy_params or {}

    if len(y_prob) == 0:
        return {"threshold": 0.5, "policy_type": policy_type, "flagged_count": 0}

    sorted_probs = np.sort(y_prob)[::-1]

    if policy_type == "capacity":
        capacity = int(policy_params.get("capacity", 20))
        if capacity >= len(sorted_probs):
            threshold = float(sorted_probs[-1])
        else:
            threshold = float(sorted_probs[capacity - 1])
        flagged = int(np.sum(y_prob >= threshold))
        return {
            "threshold": round(threshold, 4),
            "policy_type": "capacity",
            "policy_params": {"capacity": capacity},
            "flagged_count": flagged,
        }

    elif policy_type == "precision":
        target_prec = float(policy_params.get("target_precision", 0.80))
        best_t = 0.5
        if y_true is not None and len(y_true) > 0:
            thresholds = np.unique(sorted_probs)
            for t in thresholds:
                preds = (y_prob >= t).astype(int)
                tp = np.sum((preds == 1) & (y_true == 1))
                fp = np.sum((preds == 1) & (y_true == 0))
                prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
                if prec >= target_prec:
                    best_t = float(t)
                    break
        return {
            "threshold": round(best_t, 4),
            "policy_type": "precision",
            "policy_params": {"target_precision": target_prec},
            "flagged_count": int(np.sum(y_prob >= best_t)),
        }

    elif policy_type == "recall":
        target_rec = float(policy_params.get("target_recall", 0.80))
        best_t = 0.5
        if y_true is not None and len(y_true) > 0:
            thresholds = np.unique(sorted_probs)[::-1]
            for t in thresholds:
                preds = (y_prob >= t).astype(int)
                tp = np.sum((preds == 1) & (y_true == 1))
                fn = np.sum((preds == 0) & (y_true == 1))
                rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
                if rec >= target_rec:
                    best_t = float(t)
                    break
        return {
            "threshold": round(best_t, 4),
            "policy_type": "recall",
            "policy_params": {"target_recall": target_rec},
            "flagged_count": int(np.sum(y_prob >= best_t)),
        }

    else:
        fixed_t = float(policy_params.get("fixed_threshold", 0.5))
        return {
            "threshold": round(fixed_t, 4),
            "policy_type": "fixed",
            "policy_params": {"fixed_threshold": fixed_t},
            "flagged_count": int(np.sum(y_prob >= fixed_t)),
        }


def promote_risk_model(
    baseline_metrics: dict[str, Any],
    challenger_metrics: dict[str, Any],
    probability_status: str,
    margin_brier: float = 0.01,
    margin_pr_auc: float = 0.02,
) -> tuple[str, str]:
    """Candidate Promotion Rule (7.6):
    Challenger promoted over baseline only if calibrated and materially improves Brier/PR-AUC.
    """
    b_brier = baseline_metrics.get("brier_score")
    c_brier = challenger_metrics.get("brier_score")

    b_prauc = baseline_metrics.get("pr_auc")
    c_prauc = challenger_metrics.get("pr_auc")

    if probability_status != "calibrated":
        return "BaseRateClassifier", "Probability is uncalibrated; retaining baseline model."

    if c_brier is None or b_brier is None:
        return "BaseRateClassifier", "Metrics unavailable for candidate promotion; retaining baseline model."

    improved_brier = (b_brier - c_brier) >= margin_brier
    improved_prauc = (c_prauc - b_prauc) >= margin_pr_auc if (c_prauc and b_prauc) else False

    if improved_brier or improved_prauc:
        return "LogisticRegression", f"Challenger materially improved baseline (Brier diff: {b_brier - c_brier:.4f})."

    return "BaseRateClassifier", "Challenger did not materially improve baseline model performance."
