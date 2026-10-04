"""WP-03 Classification, Calibration & Threshold Policy Unit Tests."""

from __future__ import annotations

import numpy as np
import pytest

from decisionos_analytics.risk import (
    BaseRateClassifier,
    LogisticRegressionClassifier,
    PlattCalibrator,
    RandomForestChallengerClassifier,
    calculate_classification_metrics,
    determine_operating_threshold,
    promote_risk_model,
)


def sample_classification_data(n: int = 100, seed: int = 42):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 3))
    # Synthetic ground truth signal
    logits = 1.2 * X[:, 0] - 0.8 * X[:, 1]
    probs = 1.0 / (1.0 + np.exp(-logits))
    y = (probs > 0.5).astype(int)
    return X, y, probs


def test_baselines_eval_base_rate_and_logistic():
    """Verify BaseRateClassifier and LogisticRegressionClassifier fit and predict_proba."""
    X, y, _ = sample_classification_data(60)

    # 1. BaseRateClassifier
    br = BaseRateClassifier().fit(X, y)
    br_probs = br.predict_proba(X)
    assert br_probs.shape == (60, 2)
    assert np.allclose(br_probs[:, 1], np.mean(y))

    # 2. LogisticRegressionClassifier
    lr = LogisticRegressionClassifier().fit(X, y)
    lr_probs = lr.predict_proba(X)
    assert lr_probs.shape == (60, 2)
    assert np.all((lr_probs[:, 1] >= 0.0) & (lr_probs[:, 1] <= 1.0))

    # 3. RandomForestChallengerClassifier
    rf = RandomForestChallengerClassifier().fit(X, y)
    rf_probs = rf.predict_proba(X)
    assert rf_probs.shape == (60, 2)


def test_platt_probability_calibration():
    """Verify Platt scaling uses separate validation data and sets probability_status."""
    X_train, y_train, _ = sample_classification_data(50, seed=1)
    X_val, y_val, _ = sample_classification_data(30, seed=2)

    # Fit model on training
    lr = LogisticRegressionClassifier().fit(X_train, y_train)
    raw_val_probs = lr.predict_proba(X_val)[:, 1]

    # Fit calibrator on validation
    calibrator = PlattCalibrator().fit(raw_val_probs, y_val)
    assert calibrator.is_calibrated is True
    assert calibrator.probability_status == "calibrated"

    calib_probs = calibrator.transform(raw_val_probs)
    assert len(calib_probs) == 30
    assert np.all((calib_probs >= 0.0) & (calib_probs <= 1.0))

    # Insufficient validation samples -> uncalibrated
    small_calibrator = PlattCalibrator(min_calib_samples=100).fit(raw_val_probs, y_val)
    assert small_calibrator.is_calibrated is False
    assert small_calibrator.probability_status == "uncalibrated"


def test_threshold_policy_capacity_based():
    """Verify capacity-based operational threshold selection (e.g. top 20 cases)."""
    scores = np.linspace(0.01, 0.99, 100)  # 100 cases with scores 0.01..0.99

    # Capacity = top 20 cases
    res = determine_operating_threshold(scores, policy_type="capacity", policy_params={"capacity": 20})
    assert res["policy_type"] == "capacity"
    assert res["flagged_count"] == 20
    assert res["threshold"] == round(float(np.sort(scores)[-20]), 4)
    assert res["threshold"] != 0.5

    # Capacity = top 5 cases
    res5 = determine_operating_threshold(scores, policy_type="capacity", policy_params={"capacity": 5})
    assert res5["flagged_count"] == 5


def test_candidate_promotion_rule():
    """Verify candidate promotion requires calibration and material baseline improvement."""
    base_metrics = {"brier_score": 0.20, "pr_auc": 0.40}
    good_challenger = {"brier_score": 0.12, "pr_auc": 0.65}
    weak_challenger = {"brier_score": 0.198, "pr_auc": 0.41}

    # 1. Uncalibrated -> retains baseline
    prom_uncal, reason1 = promote_risk_model(base_metrics, good_challenger, probability_status="uncalibrated")
    assert prom_uncal == "BaseRateClassifier"
    assert "uncalibrated" in reason1

    # 2. Calibrated and good improvement -> promotes LogisticRegression
    prom_good, reason2 = promote_risk_model(base_metrics, good_challenger, probability_status="calibrated")
    assert prom_good == "LogisticRegression"
    assert "improved baseline" in reason2

    # 3. Calibrated but weak improvement -> retains BaseRateClassifier
    prom_weak, reason3 = promote_risk_model(base_metrics, weak_challenger, probability_status="calibrated")
    assert prom_weak == "BaseRateClassifier"
    assert "did not materially improve" in reason3


def test_classification_metrics_report():
    """Verify comprehensive metrics calculation: Brier, ROC-AUC, PR-AUC, precision, recall."""
    y_true = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    y_prob = np.array([0.1, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.9])

    metrics = calculate_classification_metrics(y_true, y_prob, threshold=0.5)
    assert metrics["sample_count"] == 8
    assert metrics["positive_event_count"] == 4
    assert metrics["prevalence"] == 0.5
    assert metrics["brier_score"] is not None
    assert metrics["roc_auc"] == 1.0
    assert metrics["pr_auc"] == 1.0
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["confusion_matrix"]["tp"] == 4
    assert metrics["confusion_matrix"]["fp"] == 0
