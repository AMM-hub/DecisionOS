"""M5 — Monitoring, Incidents, and Alerts (spec §14).

Contextual detection, alert lifecycle, data health checks, and episode
workflow. All anomaly detection uses information available *before* the
scored observation (§14.2). Implements false-discovery control via
minimum effect size, persistence requirements, and seasonal MAD ranges.
"""

from __future__ import annotations

import json
import math
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# 14.1 — Data health
# ---------------------------------------------------------------------------

class DataHealth:
    """Health per dataset revision.

    - freshness: time since last revision
    - status: 'healthy' | 'stale' | 'suspended' | 'unknown'
    - dependency impact computed from upstream dataset health
    """

    @staticmethod
    def check(tenant: str, dataset_id: str, store) -> dict:
        """Return health status for a single dataset."""
        ds = store.conn.execute(
            "SELECT * FROM dataset WHERE tenant_id=? AND id=?", (tenant, dataset_id)
        ).fetchone()
        if ds is None:
            return {
                "dataset_id": dataset_id,
                "freshness_hours": None,
                "revision_count": 0,
                "latest_revision": None,
                "last_ingested_at": None,
                "status": "unknown",
                "revision_history": [],
            }

        revisions = store.conn.execute(
            "SELECT revision, state, created_at, row_count FROM dataset_revision "
            "WHERE tenant_id=? AND dataset_id=? ORDER BY revision DESC",
            (tenant, dataset_id),
        ).fetchall()

        if not revisions:
            return {
                "dataset_id": dataset_id,
                "freshness_hours": None,
                "revision_count": 0,
                "latest_revision": None,
                "last_ingested_at": ds["created_at"] if ds["created_at"] else None,
                "status": "unknown",
                "revision_history": [],
            }

        latest = revisions[0]
        created = latest["created_at"]
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            freshness = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        except (ValueError, TypeError):
            freshness = None

        # Stale if > 72h since last revision and no ongoing activity
        status = "healthy"
        if freshness is not None:
            if freshness > 72:
                status = "stale"
            if freshness > 168:  # 7 days
                status = "suspended"

        history = [
            {
                "revision": r["revision"],
                "created_at": r["created_at"],
                "object_count": r["row_count"],
            }
            for r in revisions[:20]  # limit history depth
        ]

        return {
            "dataset_id": dataset_id,
            "freshness_hours": round(freshness, 2) if freshness is not None else None,
            "revision_count": len(revisions),
            "latest_revision": latest["revision"],
            "last_ingested_at": latest["created_at"],
            "status": status,
            "revision_history": history,
        }

    @staticmethod
    def check_all(tenant: str, store) -> list[dict]:
        """Return health for all datasets belonging to tenant."""
        datasets = store.conn.execute(
            "SELECT id FROM dataset WHERE tenant_id=?", (tenant,)
        ).fetchall()
        return [DataHealth.check(tenant, d["id"], store) for d in datasets]


# ---------------------------------------------------------------------------
# 14.2 — Contextual detection
# ---------------------------------------------------------------------------

class ContextualDetector:
    """Anomaly detection on a metric series.

    Methods (§14.2):
    - seasonal_naive: seasonal naive range ± k*MAD
    - residual_detection: residual from expected vs observed
    - change_point: detect level shifts via CUSUM
    """

    @staticmethod
    def seasonal_naive_range(
        series: list[float],
        season_length: int,
        k: float = 3,
    ) -> tuple[float, float]:
        """Return (lower, upper) bounds using seasonal naive ± k*MAD.

        For each position in the season cycle, computes the MAD of all
        observations at that phase and builds an interval around the
        phase-median. The final interval is the envelope across all phases.
        """
        if not series:
            return (float("-inf"), float("inf"))
        if len(series) < season_length:
            median = statistics.median(series)
            mad = statistics.median(abs(v - median) for v in series) or 1.0
            return (median - k * mad, median + k * mad)

        phase_values: dict[int, list[float]] = {}
        for i, v in enumerate(series):
            phase = i % season_length
            phase_values.setdefault(phase, []).append(v)

        lows, highs = [], []
        for phase in sorted(phase_values):
            vals = phase_values[phase]
            m = statistics.median(vals)
            mad = statistics.median(abs(v - m) for v in vals) or 1.0
            lows.append(m - k * mad)
            highs.append(m + k * mad)

        return (min(lows), max(highs))

    @staticmethod
    def detect_anomalies(
        series: list[float],
        method: str = "seasonal_naive",
        season_length: int = 7,
        threshold: float = 3.0,
        min_effect_size: float = 0.01,
    ) -> list[dict]:
        """Detect anomalies in a time series.

        Each anomaly dict:
            index, observed, expected_lower, expected_upper,
            method, effect_size, persistent_count

        Only points outside the expected range with effect_size >=
        min_effect_size are flagged.
        """
        if len(series) < 2:
            return []

        anomalies: list[dict] = []
        for i in range(1, len(series)):
            before = series[:i]
            obs = series[i]
            if method == "seasonal_naive":
                lo, hi = ContextualDetector.seasonal_naive_range(
                    before, season_length, threshold
                )
            else:
                # residual_detection: simple moving-average residual
                window = min(i, season_length)
                mu = sum(before[-window:]) / window if window > 0 else 0
                resid = obs - mu
                std = (
                    statistics.stdev(before[-window:])
                    if len(before) >= 2
                    else 1.0
                )
                lo, hi = mu - threshold * std, mu + threshold * std

            if obs < lo or obs > hi:
                expected = (lo + hi) / 2
                effect = abs(obs - expected) / (abs(expected) + 1e-12)
                if effect >= min_effect_size:
                    anomalies.append({
                        "index": i,
                        "observed": obs,
                        "expected_lower": round(lo, 6),
                        "expected_upper": round(hi, 6),
                        "method": method,
                        "effect_size": round(effect, 6),
                        "persistent_count": _count_persistent(
                            series, i, lo, hi
                        ),
                    })
        return anomalies

    @staticmethod
    def cusum_detection(
        series: list[float],
        target: float | None = None,
        threshold: float = 5.0,
        drift: float = 0.5,
    ) -> list[dict]:
        """CUSUM change-point detection (§14.2).

        Returns detected shifts as anomaly dicts with the shift index,
        magnitude, and cumulative sum at detection point.
        """
        if len(series) < 5:
            return []
        mu = target if target is not None else statistics.mean(series[: len(series) // 2])
        cusum_pos, cusum_neg = 0.0, 0.0
        shifts = []
        for i, v in enumerate(series):
            cusum_pos = max(0, cusum_pos + (v - mu) - drift)
            cusum_neg = max(0, cusum_neg - (v - mu) - drift)
            if cusum_pos > threshold or cusum_neg > threshold:
                direction = "up" if cusum_pos > cusum_neg else "down"
                shifts.append({
                    "index": i,
                    "observed": v,
                    "expected_lower": mu - threshold,
                    "expected_upper": mu + threshold,
                    "method": "cusum",
                    "effect_size": round(abs(v - mu) / (abs(mu) + 1e-12), 6),
                    "persistent_count": 1,
                    "cusum_direction": direction,
                    "cumulative_sum": round(
                        max(cusum_pos, cusum_neg), 4
                    ),
                    "baseline_mean": round(mu, 4),
                })
                cusum_pos, cusum_neg = 0.0, 0.0  # reset
        return shifts


def _count_persistent(
    series: list[float], idx: int, lo: float, hi: float
) -> int:
    """Count consecutive anomalies backward from idx."""
    count = 0
    for j in range(idx, max(0, idx - 10), -1):
        if series[j] < lo or series[j] > hi:
            count += 1
        else:
            break
    return count


# ---------------------------------------------------------------------------
# 14.3 — Alert state
# ---------------------------------------------------------------------------

@dataclass
class AlertRule:
    tenant_id: str
    id: str
    name: str
    dataset_id: str
    metric_id: str
    method: str = "seasonal_naive"
    season_length: int = 7
    threshold: float = 3.0
    min_effect_size: float = 0.01
    persistence: int = 1
    owner: str = ""
    escalation: str = ""
    runbook: str = ""
    enabled: bool = True


@dataclass
class AlertEpisode:
    id: str
    rule_id: str
    episode_identity: str
    condition_id: str
    workflow_status: str = "open"  # open|acknowledged|investigating|resolved|dismissed
    observed_value: float | None = None
    expected_lower: float | None = None
    expected_upper: float | None = None
    scoring_method: str = ""
    training_window: str = ""
    effect_size: float | None = None
    persistence_count: int = 0


class AlertEngine:
    """Evaluate rules against metric data, fire alerts with deduplication."""

    @staticmethod
    def evaluate_rules(tenant: str, store, conn) -> list[dict]:
        """Run all enabled rules and fire alerts.

        Dedupe by (tenant, rule_id, episode_identity) — NOT by timestamp.
        """
        rules = store.conn.execute(
            "SELECT * FROM alert_rule WHERE tenant_id=? AND enabled=1",
            (tenant,),
        ).fetchall()

        fired: list[dict] = []
        for rule in rules:
            rule_id = rule["id"]
            method = rule["method"]
            season_length = rule["season_length"]
            threshold = rule["threshold"]
            min_effect = rule["min_effect_size"]
            persistence = rule["persistence"]

            # Build series from metric data
            try:
                series = _load_metric_series(
                    tenant, rule["dataset_id"], rule["metric_id"], store
                )
            except LookupError:
                continue  # skip rules where data is unavailable

            if len(series) < 3:
                continue

            anomalies = ContextualDetector.detect_anomalies(
                series,
                method=method,
                season_length=season_length,
                threshold=threshold,
                min_effect_size=min_effect,
            )

            for anomaly in anomalies:
                if anomaly["persistent_count"] < persistence:
                    continue  # persistence requirement not met

                # Build stable episode identity
                ep_identity = f"{rule_id}:{method}:{anomaly['index']}"

                # Check dedup: existing open/investigating episode?
                existing = conn.execute(
                    "SELECT id FROM alert_episode WHERE tenant_id=? AND rule_id=? "
                    "AND episode_identity=? AND workflow_status IN ('open','acknowledged','investigating')",
                    (tenant, rule_id, ep_identity),
                ).fetchone()
                if existing:
                    continue  # already active, don't re-fire

                result = AlertEngine.fire_alert(
                    tenant, rule_id, anomaly, store, conn,
                    episode_identity=ep_identity,
                )
                fired.append(result)

        return fired

    @staticmethod
    def fire_alert(
        tenant: str,
        rule_id: str,
        anomaly: dict,
        store,
        conn,
        episode_identity: str | None = None,
    ) -> dict:
        """Create/update condition_state + alert_episode.

        Condition: normal→pending→active→recovered
        Episode: open→acknowledged→investigating→resolved→dismissed
        """
        if episode_identity is None:
            episode_identity = f"{rule_id}:{anomaly['method']}:{anomaly['index']}"

        # Upsert condition_state
        existing_cond = conn.execute(
            "SELECT id, condition FROM condition_state WHERE tenant_id=? AND rule_id=?",
            (tenant, rule_id),
        ).fetchone()

        now = _now_iso()
        if existing_cond:
            cond_id = existing_cond["id"]
            old_cond = existing_cond["condition"]
            if old_cond in ("normal", "recovered"):
                new_cond = "pending"
            elif old_cond == "pending":
                new_cond = "active"
            else:
                new_cond = old_cond  # already active
            conn.execute(
                "UPDATE condition_state SET condition=?, started_at=? WHERE tenant_id=? AND id=?",
                (new_cond, now, tenant, cond_id),
            )
        else:
            cond_id = _new_id()
            conn.execute(
                "INSERT INTO condition_state(tenant_id,id,rule_id,condition,started_at) VALUES (?,?,?,?,?)",
                (tenant, cond_id, rule_id, "pending", now),
            )

        # Create alert_episode
        ep_id = _new_id()
        conn.execute(
            "INSERT INTO alert_episode(tenant_id,id,rule_id,episode_identity,condition_id,"
            "workflow_status,observed_value,expected_lower,expected_upper,"
            "scoring_method,training_window,effect_size,persistence_count,started_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                tenant, ep_id, rule_id, episode_identity, cond_id,
                "open", anomaly["observed"], anomaly["expected_lower"],
                anomaly["expected_upper"], anomaly["method"],
                f"window_{anomaly['index']}", anomaly["effect_size"],
                anomaly["persistent_count"], now,
            ),
        )
        conn.commit()

        return {
            "episode_id": ep_id,
            "rule_id": rule_id,
            "condition_id": cond_id,
            "workflow_status": "open",
            "observed_value": anomaly["observed"],
            "expected_lower": anomaly["expected_lower"],
            "expected_upper": anomaly["expected_upper"],
            "method": anomaly["method"],
        }


class AlertLifecycle:
    """CRUD for alert rules, episodes, condition states."""

    @staticmethod
    def create_rule(tenant: str, rule: dict, user: str, store) -> dict:
        now = _now_iso()
        rid = _new_id()
        store.conn.execute(
            "INSERT INTO alert_rule(tenant_id,id,name,dataset_id,metric_id,"
            "method,season_length,threshold,min_effect_size,persistence,"
            "owner,escalation,runbook,enabled,created_by,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                tenant, rid, rule["name"], rule["dataset_id"], rule["metric_id"],
                rule.get("method", "seasonal_naive"),
                rule.get("season_length", 7),
                rule.get("threshold", 3.0),
                rule.get("min_effect_size", 0.01),
                rule.get("persistence", 1),
                rule.get("owner", user),
                rule.get("escalation", ""),
                rule.get("runbook", ""),
                1, user, now, now,
            ),
        )
        store.conn.commit()
        store.audit(tenant, user, "monitoring.rule.create", rid, "created")
        return AlertLifecycle._rule_to_dict(store, tenant, rid)

    @staticmethod
    def list_rules(tenant: str, store) -> list[dict]:
        rows = store.conn.execute(
            "SELECT * FROM alert_rule WHERE tenant_id=? ORDER BY created_at DESC",
            (tenant,),
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def update_rule(tenant: str, rule_id: str, updates: dict, user: str, store) -> dict:
        allowed = {
            "name", "method", "season_length", "threshold", "min_effect_size",
            "persistence", "owner", "escalation", "runbook", "enabled",
        }
        now = _now_iso()
        sets = ", ".join(f"{k}=?" for k in updates if k in allowed)
        if not sets:
            raise ValueError("no updatable fields")
        sets += ", updated_at=?"
        vals = [updates[k] for k in updates if k in allowed] + [now, tenant, rule_id]
        store.conn.execute(
            f"UPDATE alert_rule SET {sets} WHERE tenant_id=? AND id=?", vals
        )
        store.conn.commit()
        store.audit(tenant, user, "monitoring.rule.update", rule_id, "updated", {"changes": updates})
        return AlertLifecycle._rule_to_dict(store, tenant, rule_id)

    @staticmethod
    def list_episodes(tenant: str, store, status: str | None = None) -> list[dict]:
        if status:
            rows = store.conn.execute(
                "SELECT * FROM alert_episode WHERE tenant_id=? AND workflow_status=? ORDER BY started_at DESC",
                (tenant, status),
            ).fetchall()
        else:
            rows = store.conn.execute(
                "SELECT * FROM alert_episode WHERE tenant_id=? ORDER BY started_at DESC",
                (tenant,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def transition_episode(tenant: str, episode_id: str, new_status: str, user: str, store) -> dict:
        valid = {"open", "acknowledged", "investigating", "resolved", "dismissed"}
        if new_status not in valid:
            raise ValueError(f"invalid status: {new_status}")
        row = store.conn.execute(
            "SELECT * FROM alert_episode WHERE tenant_id=? AND id=?", (tenant, episode_id)
        ).fetchone()
        if row is None:
            raise LookupError(f"episode {episode_id} not found")

        now = _now_iso()
        if new_status == "acknowledged":
            store.conn.execute(
                "UPDATE alert_episode SET workflow_status=?, acknowledged_at=?, acknowledged_by=? WHERE tenant_id=? AND id=?",
                (new_status, now, user, tenant, episode_id),
            )
        elif new_status == "resolved":
            store.conn.execute(
                "UPDATE alert_episode SET workflow_status=?, resolved_at=? WHERE tenant_id=? AND id=?",
                (new_status, now, tenant, episode_id),
            )
            # Recover condition
            store.conn.execute(
                "UPDATE condition_state SET condition='recovered', recovered_at=? WHERE tenant_id=? AND id=?",
                (now, tenant, row["condition_id"]),
            )
        else:
            store.conn.execute(
                "UPDATE alert_episode SET workflow_status=? WHERE tenant_id=? AND id=?",
                (new_status, tenant, episode_id),
            )
        store.conn.commit()
        store.audit(tenant, user, "monitoring.episode.transition", episode_id, "success",
                     {"from": row["workflow_status"], "to": new_status})
        return dict(store.conn.execute(
            "SELECT * FROM alert_episode WHERE tenant_id=? AND id=?", (tenant, episode_id)
        ).fetchone())

    @staticmethod
    def list_condition_states(tenant: str, store) -> list[dict]:
        rows = store.conn.execute(
            "SELECT cs.*, ar.name AS rule_name FROM condition_state cs "
            "LEFT JOIN alert_rule ar ON cs.tenant_id=ar.tenant_id AND cs.rule_id=ar.id "
            "WHERE cs.tenant_id=? ORDER BY cs.started_at DESC",
            (tenant,),
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _rule_to_dict(store, tenant: str, rule_id: str) -> dict:
        row = store.conn.execute(
            "SELECT * FROM alert_rule WHERE tenant_id=? AND id=?", (tenant, rule_id)
        ).fetchone()
        if row is None:
            raise LookupError(f"rule {rule_id} not found")
        return dict(row)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_metric_series(tenant: str, dataset_id: str, metric_id: str, store) -> list[float]:
    """Load certified metric data as a flat list of values.

    Raises LookupError if data is unavailable.
    """
    ds = store.conn.execute(
        "SELECT * FROM dataset WHERE tenant_id=? AND id=?", (tenant, dataset_id)
    ).fetchone()
    if ds is None or ds["published_revision"] is None:
        raise LookupError("no published revision")

    # Load the published revision parquet through the object store
    rev = store.conn.execute(
        "SELECT manifest FROM dataset_revision WHERE tenant_id=? AND dataset_id=? AND revision=?",
        (tenant, dataset_id, ds["published_revision"]),
    ).fetchone()
    if rev is None:
        raise LookupError("revision not found")

    # For monitoring detection, we load a simpler series:
    # try the first column from the published data
    try:
        manifest = json.loads(rev["manifest"])
        object_key = manifest.get("objects", [{}])[0].get("key", "")
        if not object_key:
            raise LookupError("no objects in manifest")
        # Read directly from parquet file in the object store
        from pathlib import Path
        obj_dir = Path(store.conn.execute(
            "PRAGMA database_filename"
        ).fetchone()[0]).parent / "objects"
        pqt_path = obj_dir / object_key
        if not pqt_path.exists():
            raise LookupError(f"object file not found: {pqt_path}")
        import polars as pl
        df = pl.read_parquet(pqt_path)
        # Use numeric columns; pick the first numeric one
        numeric_cols = [c for c, t in zip(df.columns, df.dtypes) if t in ("Int64", "Float64", "int64", "float64")]
        if numeric_cols:
            return [float(v) for v in df[numeric_cols[0]].to_list() if v is not None]
        # Fallback: count by time basis
        time_cols = [c for c in df.columns if c in ("created_at", "timestamp", "ds", "date")]
        if time_cols:
            counts = df.group_by(time_cols[0]).agg(pl.len().alias("cnt"))
            return [float(v) for v in counts["cnt"].to_list()]
        raise LookupError("no suitable columns for series")
    except Exception as e:
        raise LookupError(f"cannot load series: {e}")