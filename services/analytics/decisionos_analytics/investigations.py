"""D2 Investigation Workspace & Structured Claims Engine (spec §10, §14, §15).

Preserves incident review analytical states, structured claim facts, and idempotent
launch linkage from monitoring episodes and workflow bottlenecks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .evidence import EvidenceType, SupportStatus
from .store import Store, new_id, now_iso


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class InvestigationStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class SourceType(str, Enum):
    MONITORING_EPISODE = "monitoring_episode"
    WORKFLOW_BOTTLENECK = "workflow_bottleneck"
    AD_HOC = "ad_hoc"


VALID_STATUS_TRANSITIONS = {
    InvestigationStatus.OPEN: {InvestigationStatus.IN_PROGRESS, InvestigationStatus.RESOLVED, InvestigationStatus.CLOSED},
    InvestigationStatus.IN_PROGRESS: {InvestigationStatus.RESOLVED, InvestigationStatus.CLOSED, InvestigationStatus.OPEN},
    InvestigationStatus.RESOLVED: {InvestigationStatus.CLOSED, InvestigationStatus.IN_PROGRESS, InvestigationStatus.OPEN},
    InvestigationStatus.CLOSED: {InvestigationStatus.OPEN},  # Reopen
}


class InvestigationError(Exception):
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


# ---------------------------------------------------------------------------
# Core Operations
# ---------------------------------------------------------------------------

def create_investigation(
    store: Store,
    tenant_id: str,
    title: str,
    question: str,
    owner: str,
    user_id: str,
    source_type: SourceType = SourceType.AD_HOC,
    source_id: str | None = None,
    analytical_state: dict[str, Any] | None = None,
    alternative_explanations: list[str] | None = None,
) -> dict:
    inv_id = f"inv-{new_id()[:12]}"
    created_at = now_iso()
    updated_at = created_at

    # If source_id is provided, validate non-cross tenant source existence where applicable
    if source_id and source_type == SourceType.MONITORING_EPISODE:
        ep = store.conn.execute(
            "SELECT id FROM alert_episode WHERE tenant_id=? AND id=?",
            (tenant_id, source_id),
        ).fetchone()
        if ep is None:
            raise InvestigationError("source_not_found", "Monitoring episode source not found")

    store.conn.execute(
        """INSERT INTO investigation(
            tenant_id, id, title, question, source_type, source_id, status, owner,
            analytical_state_json, alternative_explanations_json, created_by, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            tenant_id,
            inv_id,
            title,
            question,
            source_type.value,
            source_id,
            InvestigationStatus.OPEN.value,
            owner,
            json.dumps(analytical_state or {}),
            json.dumps(alternative_explanations or []),
            user_id,
            created_at,
            updated_at,
        ),
    )
    store.conn.commit()

    store.audit(tenant_id, user_id, "investigation.create", inv_id, "created", {"title": title, "source_type": source_type.value})
    return get_investigation(store, tenant_id, inv_id)


def list_investigations(
    store: Store,
    tenant_id: str,
    status: str | None = None,
    owner: str | None = None,
    source_type: str | None = None,
) -> list[dict]:
    query = "SELECT * FROM investigation WHERE tenant_id=?"
    params: list[Any] = [tenant_id]

    if status:
        query += " AND status=?"
        params.append(status)
    if owner:
        query += " AND owner=?"
        params.append(owner)
    if source_type:
        query += " AND source_type=?"
        params.append(source_type)

    query += " ORDER BY updated_at DESC"
    rows = store.conn.execute(query, params).fetchall()

    results = []
    for r in rows:
        d = dict(r)
        d["analytical_state"] = json.loads(d["analytical_state_json"])
        d["alternative_explanations"] = json.loads(d["alternative_explanations_json"])
        results.append(d)
    return results


def get_investigation(
    store: Store,
    tenant_id: str,
    investigation_id: str,
) -> dict:
    row = store.conn.execute(
        "SELECT * FROM investigation WHERE tenant_id=? AND id=?",
        (tenant_id, investigation_id),
    ).fetchone()
    if row is None:
        raise InvestigationError("investigation_not_found", "Investigation not found")

    inv = dict(row)
    inv["analytical_state"] = json.loads(inv["analytical_state_json"])
    inv["alternative_explanations"] = json.loads(inv["alternative_explanations_json"])

    # Fetch claims
    claims_rows = store.conn.execute(
        "SELECT * FROM investigation_claim WHERE tenant_id=? AND investigation_id=? ORDER BY created_at ASC",
        (tenant_id, investigation_id),
    ).fetchall()
    claims = []
    for c in claims_rows:
        cd = dict(c)
        cd["quality_flags"] = json.loads(cd["quality_flags_json"])
        cd["structured_fact"] = json.loads(cd["structured_fact_json"])
        claims.append(cd)
    inv["claims"] = claims

    # Fetch linked evidence artifacts
    ev_rows = store.conn.execute(
        "SELECT id, evidence_type, support_status, metric_id, dataset_id, canonical_digest, created_at FROM evidence_artifact WHERE tenant_id=? AND investigation_id=?",
        (tenant_id, investigation_id),
    ).fetchall()
    inv["evidence_artifacts"] = [dict(ev) for ev in ev_rows]

    return inv


def update_investigation_status(
    store: Store,
    tenant_id: str,
    investigation_id: str,
    new_status: InvestigationStatus | str,
    user_id: str,
) -> dict:
    inv = get_investigation(store, tenant_id, investigation_id)
    current_status = InvestigationStatus(inv["status"])
    if isinstance(new_status, str):
        try:
            new_status = InvestigationStatus(new_status)
        except ValueError:
            raise InvestigationError("invalid_status", f"Invalid status '{new_status}'")

    if new_status not in VALID_STATUS_TRANSITIONS.get(current_status, set()):
        raise InvestigationError(
            "invalid_transition",
            f"Cannot transition investigation from '{current_status.value}' to '{new_status.value}'",
        )

    now = now_iso()
    store.conn.execute(
        "UPDATE investigation SET status=?, updated_at=? WHERE tenant_id=? AND id=?",
        (new_status.value, now, tenant_id, investigation_id),
    )
    store.conn.commit()

    store.audit(tenant_id, user_id, "investigation.status_change", investigation_id, "success", {"from": current_status.value, "to": new_status.value})
    return get_investigation(store, tenant_id, investigation_id)


def add_claim(
    store: Store,
    tenant_id: str,
    investigation_id: str,
    statement: str,
    user_id: str,
    evidence_type: EvidenceType = EvidenceType.OBSERVED,
    support_status: SupportStatus = SupportStatus.SUPPORTING,
    quality_flags: list[str] | None = None,
    structured_fact: dict[str, Any] | None = None,
    evidence_id: str | None = None,
) -> dict:
    # 1. Verify investigation ownership
    get_investigation(store, tenant_id, investigation_id)

    # 2. Verify evidence ownership if referenced
    if evidence_id:
        ev = store.conn.execute(
            "SELECT id FROM evidence_artifact WHERE tenant_id=? AND id=? AND investigation_id=?",
            (tenant_id, evidence_id, investigation_id),
        ).fetchone()
        if ev is None:
            raise InvestigationError("evidence_not_found", "Referenced evidence artifact not found in this investigation")

    claim_id = f"clm-{new_id()[:12]}"
    created_at = now_iso()

    store.conn.execute(
        """INSERT INTO investigation_claim(
            tenant_id, id, investigation_id, evidence_id, statement, evidence_type,
            support_status, quality_flags_json, structured_fact_json, created_by, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            tenant_id,
            claim_id,
            investigation_id,
            evidence_id,
            statement,
            evidence_type.value,
            support_status.value,
            json.dumps(quality_flags or []),
            json.dumps(structured_fact or {}),
            user_id,
            created_at,
        ),
    )
    # Touch investigation updated_at
    store.conn.execute(
        "UPDATE investigation SET updated_at=? WHERE tenant_id=? AND id=?",
        (created_at, tenant_id, investigation_id),
    )
    store.conn.commit()

    store.audit(tenant_id, user_id, "claim.add", claim_id, "added", {"investigation_id": investigation_id})

    row = store.conn.execute("SELECT * FROM investigation_claim WHERE tenant_id=? AND id=?", (tenant_id, claim_id)).fetchone()
    res = dict(row)
    res["quality_flags"] = json.loads(res["quality_flags_json"])
    res["structured_fact"] = json.loads(res["structured_fact_json"])
    return res


def investigate_episode(
    store: Store,
    tenant_id: str,
    episode_id: str,
    user_id: str,
) -> tuple[dict, bool]:
    """Idempotently launches an Investigation from a Monitoring Episode (spec §14, §15).
    If an investigation already exists for (tenant_id, 'monitoring_episode', episode_id),
    returns (existing_investigation, False).
    Otherwise creates a new investigation and returns (new_investigation, True).
    """
    # 1. Check if investigation already exists for episode
    existing = store.conn.execute(
        "SELECT id FROM investigation WHERE tenant_id=? AND source_type=? AND source_id=?",
        (tenant_id, SourceType.MONITORING_EPISODE.value, episode_id),
    ).fetchone()
    if existing:
        return get_investigation(store, tenant_id, existing["id"]), False

    # 2. Fetch episode details
    ep = store.conn.execute(
        "SELECT * FROM alert_episode WHERE tenant_id=? AND id=?",
        (tenant_id, episode_id),
    ).fetchone()
    if ep is None:
        raise InvestigationError("episode_not_found", "Monitoring episode not found")

    title = f"Investigation: Episode {episode_id[:8]} ({ep['rule_id'][:8]})"
    question = f"What caused the anomaly observed in rule {ep['rule_id']} (value={ep['observed_value']})?"

    inv = create_investigation(
        store=store,
        tenant_id=tenant_id,
        title=title,
        question=question,
        owner=user_id,
        user_id=user_id,
        source_type=SourceType.MONITORING_EPISODE,
        source_id=episode_id,
        analytical_state={"episode_observed_value": ep["observed_value"], "rule_id": ep["rule_id"]},
    )
    return inv, True
