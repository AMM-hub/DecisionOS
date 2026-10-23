"""M4 Decision Register (spec §19): immutable decision lifecycle with
append-only audit trail.

Lifecycle (§19.2):
  draft → proposed → accepted → implementation_pending → active →
  review_due → evaluated → closed

Additional: rejected, deferred, abandoned, superseded.

Outcome records (§19.3):
  Verdicts: supported_improvement, no_clear_change, deterioration,
            inconclusive, not_evaluable

Design principles encoded here:
1. Append-only amendments: freeze accepted context; amendments carry
   author, reason, scope, and relationship to prior version (§19.2).
2. Counterevidence checks have four states: detected, not_detected,
   not_testable, not_run (§19.1).
3. Do not auto-close overdue decisions; send reminders instead (§19.3).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# lifecycle vocabulary
# ---------------------------------------------------------------------------

class DecisionStatus(str, Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    IMPLEMENTATION_PENDING = "implementation_pending"
    ACTIVE = "active"
    REVIEW_DUE = "review_due"
    EVALUATED = "evaluated"
    CLOSED = "closed"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    ABANDONED = "abandoned"
    SUPERSEDED = "superseded"


class Verdict(str, Enum):
    SUPPORTED_IMPROVEMENT = "supported_improvement"
    NO_CLEAR_CHANGE = "no_clear_change"
    DETERIORATION = "deterioration"
    INCONCLUSIVE = "inconclusive"
    NOT_EVALUABLE = "not_evaluable"


class CounterevidenceState(str, Enum):
    DETECTED = "detected"
    NOT_DETECTED = "not_detected"
    NOT_TESTABLE = "not_testable"
    NOT_RUN = "not_run"


class BindingRole(str, Enum):
    PRIMARY_SUPPORT = "primary_support"
    CONTRIBUTING = "contributing"
    COUNTER_EVIDENCE = "counter_evidence"


FROZEN_DECISION_STATES = {
    DecisionStatus.ACCEPTED,
    DecisionStatus.IMPLEMENTATION_PENDING,
    DecisionStatus.ACTIVE,
    DecisionStatus.REVIEW_DUE,
    DecisionStatus.EVALUATED,
    DecisionStatus.CLOSED,
    DecisionStatus.SUPERSEDED,
}


VALID_TRANSITIONS = {
    DecisionStatus.DRAFT: {DecisionStatus.PROPOSED, DecisionStatus.ABANDONED, DecisionStatus.DEFERRED},
    DecisionStatus.PROPOSED: {DecisionStatus.ACCEPTED, DecisionStatus.REJECTED, DecisionStatus.DEFERRED, DecisionStatus.ABANDONED, DecisionStatus.DRAFT},
    DecisionStatus.ACCEPTED: {DecisionStatus.IMPLEMENTATION_PENDING, DecisionStatus.ACTIVE, DecisionStatus.SUPERSEDED, DecisionStatus.ABANDONED, DecisionStatus.DEFERRED},
    DecisionStatus.IMPLEMENTATION_PENDING: {DecisionStatus.ACTIVE, DecisionStatus.SUPERSEDED, DecisionStatus.ABANDONED},
    DecisionStatus.ACTIVE: {DecisionStatus.REVIEW_DUE, DecisionStatus.EVALUATED, DecisionStatus.SUPERSEDED, DecisionStatus.ABANDONED},
    DecisionStatus.REVIEW_DUE: {DecisionStatus.EVALUATED, DecisionStatus.ACTIVE, DecisionStatus.SUPERSEDED, DecisionStatus.ABANDONED},
    DecisionStatus.EVALUATED: {DecisionStatus.CLOSED, DecisionStatus.SUPERSEDED, DecisionStatus.ABANDONED},
    DecisionStatus.CLOSED: {DecisionStatus.SUPERSEDED},
    DecisionStatus.REJECTED: {DecisionStatus.DRAFT, DecisionStatus.PROPOSED},
    DecisionStatus.DEFERRED: {DecisionStatus.DRAFT, DecisionStatus.PROPOSED},
    DecisionStatus.ABANDONED: {DecisionStatus.DRAFT},
    DecisionStatus.SUPERSEDED: set(),
}


# ---------------------------------------------------------------------------
# data models
# ---------------------------------------------------------------------------


@dataclass
class DecisionBrief:
    """Problem statement with evidence references (§19.1)."""
    problem: str
    relevant_findings: list[str]
    proposed_action: str
    baseline_option: str
    scope: str
    owner: str
    trade_offs: list[str]
    assumptions: list[str]
    evidence_coverage: list[str]
    validation_plan: str
    counter_metrics: list[str]
    expected_effect: str  # unknown, deterministic, estimated, simulated


@dataclass
class CounterevidenceCheck:
    hypothesis: str
    state: CounterevidenceState
    detail: str | None = None


@dataclass
class DecisionAmendment:
    version: int
    author: str
    reason: str
    scope: str
    previous_version: int
    created_at: str
    changes: dict[str, Any] | None = None


@dataclass
class OutcomeRecord:
    observed_results: dict[str, Any]
    pinned_definition_version: int | None
    data_revision: int | None
    measurement_window: str
    expectation: str
    estimated_effect: dict[str, Any] | None
    study_run: str | None
    data_quality_caveats: list[str]
    review_verdict: Verdict
    verdict_evidence: str


@dataclass
class DecisionRecord:
    id: str
    tenant_id: str
    title: str
    status: DecisionStatus
    brief: DecisionBrief
    counterevidence: list[CounterevidenceCheck]
    amendments: list[DecisionAmendment]
    outcome: OutcomeRecord | None
    created_by: str
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# DB schema
# ---------------------------------------------------------------------------

DECISION_SCHEMA = """
CREATE TABLE IF NOT EXISTS decision (
    tenant_id TEXT NOT NULL REFERENCES tenant(id),
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    brief_json TEXT NOT NULL,
    counterevidence_json TEXT NOT NULL DEFAULT '[]',
    amendments_json TEXT NOT NULL DEFAULT '[]',
    outcome_json TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id)
);

CREATE INDEX IF NOT EXISTS idx_decision_tenant ON decision(tenant_id);
CREATE INDEX IF NOT EXISTS idx_decision_status ON decision(status);
"""


# ---------------------------------------------------------------------------
# register operations
# ---------------------------------------------------------------------------


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def create_decision(
    conn,
    tenant_id: str,
    title: str,
    brief: DecisionBrief,
    created_by: str,
    counterevidence: list[CounterevidenceCheck] | None = None,
) -> DecisionRecord:
    """Create a new decision record in draft status."""
    did = new_id()
    ts = now_iso()
    brief_json = json.dumps({
        "problem": brief.problem,
        "relevant_findings": brief.relevant_findings,
        "proposed_action": brief.proposed_action,
        "baseline_option": brief.baseline_option,
        "scope": brief.scope,
        "owner": brief.owner,
        "trade_offs": brief.trade_offs,
        "assumptions": brief.assumptions,
        "evidence_coverage": brief.evidence_coverage,
        "validation_plan": brief.validation_plan,
        "counter_metrics": brief.counter_metrics,
        "expected_effect": brief.expected_effect,
    })
    ce_json = json.dumps([
        {"hypothesis": c.hypothesis, "state": c.state.value, "detail": c.detail}
        for c in (counterevidence or [])
    ])
    conn.execute(
        "INSERT INTO decision(id, tenant_id, title, status, brief_json, counterevidence_json, amendments_json, outcome_json, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (did, tenant_id, title, "draft", brief_json, ce_json, "[]", None, created_by, ts, ts),
    )
    conn.commit()
    return DecisionRecord(
        id=did, tenant_id=tenant_id, title=title, status=DecisionStatus.DRAFT,
        brief=brief, counterevidence=counterevidence or [],
        amendments=[], outcome=None, created_by=created_by, created_at=ts, updated_at=ts,
    )


def get_decision(conn, tenant_id: str, decision_id: str) -> DecisionRecord | None:
    row = conn.execute(
        "SELECT * FROM decision WHERE tenant_id=? AND id=?", (tenant_id, decision_id)
    ).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def count_decisions(conn, tenant_id: str, q: str | None = None) -> int:
    query = "SELECT COUNT(*) c FROM decision WHERE tenant_id=?"
    params: list[Any] = [tenant_id]
    if q:
        query += " AND LOWER(title) LIKE ?"
        params.append(f"%{q.lower()}%")
    return conn.execute(query, params).fetchone()["c"]


def list_decisions(
    conn,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
    q: str | None = None,
) -> list[DecisionRecord]:
    query = "SELECT * FROM decision WHERE tenant_id=?"
    params: list[Any] = [tenant_id]
    if q:
        query += " AND LOWER(title) LIKE ?"
        params.append(f"%{q.lower()}%")
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(query, params).fetchall()
    return [_row_to_record(r) for r in rows]


def transition_status(
    conn, tenant_id: str, decision_id: str, new_status: DecisionStatus | str,
    author: str, reason: str,
) -> DecisionRecord:
    """Transition a decision's status and record an amendment."""
    rec = get_decision(conn, tenant_id, decision_id)
    if rec is None:
        raise LookupError(f"Decision {decision_id} not found")

    if isinstance(new_status, str):
        try:
            new_status = DecisionStatus(new_status)
        except ValueError:
            raise ValueError(f"Invalid status: '{new_status}'")

    current_status = rec.status
    allowed = VALID_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise ValueError(f"Invalid status transition from '{current_status.value}' to '{new_status.value}'")

    ts = now_iso()
    old_status = rec.status.value
    amendments = rec.amendments + [
        DecisionAmendment(
            version=len(rec.amendments) + 1,
            author=author,
            reason=reason,
            scope="status_change",
            previous_version=len(rec.amendments),
            created_at=ts,
            changes={"old_status": old_status, "new_status": new_status.value},
        )
    ]
    amendments_json = json.dumps([
        {
            "version": a.version, "author": a.author, "reason": a.reason,
            "scope": a.scope, "previous_version": a.previous_version,
            "created_at": a.created_at, "changes": a.changes,
        }
        for a in amendments
    ])
    conn.execute(
        "UPDATE decision SET status=?, amendments_json=?, updated_at=? WHERE tenant_id=? AND id=?",
        (new_status.value, amendments_json, ts, tenant_id, decision_id),
    )
    conn.commit()
    rec.status = new_status
    rec.amendments = amendments
    rec.updated_at = ts
    return rec


def bind_evidence(
    conn,
    tenant_id: str,
    decision_id: str,
    evidence_id: str,
    binding_role: BindingRole,
    bound_by: str,
) -> dict[str, Any]:
    """Bind an immutable evidence artifact to a decision. Fails if decision is frozen."""
    rec = get_decision(conn, tenant_id, decision_id)
    if rec is None:
        raise LookupError(f"Decision {decision_id} not found")

    if rec.status in FROZEN_DECISION_STATES:
        raise ValueError(f"Decision {decision_id} is in status '{rec.status.value}' and context is frozen. Create an amendment to modify context.")

    # Check evidence exists for tenant
    ev_row = conn.execute(
        "SELECT id FROM evidence_artifact WHERE tenant_id=? AND id=?",
        (tenant_id, evidence_id),
    ).fetchone()
    if ev_row is None:
        raise LookupError(f"Evidence artifact {evidence_id} not found for tenant")

    # Check if duplicate binding exists
    existing = conn.execute(
        "SELECT * FROM decision_evidence_binding WHERE tenant_id=? AND decision_id=? AND evidence_id=?",
        (tenant_id, decision_id, evidence_id),
    ).fetchone()
    if existing:
        if existing["binding_role"] == binding_role.value:
            return dict(existing)
        else:
            raise ValueError(f"Evidence {evidence_id} already bound to decision {decision_id} with role '{existing['binding_role']}'")

    bind_id = new_id()
    ts = now_iso()
    conn.execute(
        "INSERT INTO decision_evidence_binding(id, tenant_id, decision_id, evidence_id, binding_role, bound_by, bound_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (bind_id, tenant_id, decision_id, evidence_id, binding_role.value, bound_by, ts),
    )
    conn.commit()
    return {
        "id": bind_id,
        "tenant_id": tenant_id,
        "decision_id": decision_id,
        "evidence_id": evidence_id,
        "binding_role": binding_role.value,
        "bound_by": bound_by,
        "bound_at": ts,
    }


def count_decision_evidence(conn, tenant_id: str, decision_id: str) -> int:
    rec = get_decision(conn, tenant_id, decision_id)
    if rec is None:
        raise LookupError(f"Decision {decision_id} not found")
    return conn.execute(
        "SELECT COUNT(*) c FROM decision_evidence_binding WHERE tenant_id=? AND decision_id=?",
        (tenant_id, decision_id),
    ).fetchone()["c"]


def list_decision_evidence(
    conn,
    tenant_id: str,
    decision_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List all evidence artifacts bound to a decision."""
    rec = get_decision(conn, tenant_id, decision_id)
    if rec is None:
        raise LookupError(f"Decision {decision_id} not found")

    rows = conn.execute(
        """
        SELECT b.id, b.tenant_id, b.decision_id, b.evidence_id, b.binding_role, b.bound_by, b.bound_at,
               e.evidence_type, e.support_status, e.canonical_digest, e.quality_flags_json, e.exactness_class, e.reproducibility_status
        FROM decision_evidence_binding b
        JOIN evidence_artifact e ON b.tenant_id = e.tenant_id AND b.evidence_id = e.id
        WHERE b.tenant_id=? AND b.decision_id=?
        ORDER BY b.bound_at ASC
        LIMIT ? OFFSET ?
        """,
        (tenant_id, decision_id, limit, offset),
    ).fetchall()

    return [
        {
            "id": r["id"],
            "tenant_id": r["tenant_id"],
            "decision_id": r["decision_id"],
            "evidence_id": r["evidence_id"],
            "binding_role": r["binding_role"],
            "bound_by": r["bound_by"],
            "bound_at": r["bound_at"],
            "evidence": {
                "artifact_id": r["evidence_id"],
                "evidence_type": r["evidence_type"],
                "support_status": r["support_status"],
                "canonical_digest": r["canonical_digest"],
                "quality_flags": json.loads(r["quality_flags_json"] or "[]"),
                "exactness_class": r["exactness_class"],
                "reproducibility_status": r["reproducibility_status"],
            },
        }
        for r in rows
    ]


def add_amendment(
    conn,
    tenant_id: str,
    decision_id: str,
    author: str,
    reason: str,
    scope: str,
    changes: dict[str, Any] | None = None,
) -> DecisionRecord:
    """Record an amendment on a decision."""
    rec = get_decision(conn, tenant_id, decision_id)
    if rec is None:
        raise LookupError(f"Decision {decision_id} not found")

    ts = now_iso()
    amendment = DecisionAmendment(
        version=len(rec.amendments) + 1,
        author=author,
        reason=reason,
        scope=scope,
        previous_version=len(rec.amendments),
        created_at=ts,
        changes=changes or {},
    )
    amendments = rec.amendments + [amendment]
    amendments_json = json.dumps([
        {
            "version": a.version, "author": a.author, "reason": a.reason,
            "scope": a.scope, "previous_version": a.previous_version,
            "created_at": a.created_at, "changes": a.changes,
        }
        for a in amendments
    ])
    conn.execute(
        "UPDATE decision SET amendments_json=?, updated_at=? WHERE tenant_id=? AND id=?",
        (amendments_json, ts, tenant_id, decision_id),
    )
    conn.commit()
    rec.amendments = amendments
    rec.updated_at = ts
    return rec


def record_outcome(
    conn, tenant_id: str, decision_id: str, outcome: OutcomeRecord,
    author: str, reason: str,
) -> DecisionRecord:
    """Record an outcome and transition to evaluated."""
    rec = get_decision(conn, tenant_id, decision_id)
    if rec is None:
        raise LookupError(f"Decision {decision_id} not found")

    ts = now_iso()
    outcome_json = json.dumps({
        "observed_results": outcome.observed_results,
        "pinned_definition_version": outcome.pinned_definition_version,
        "data_revision": outcome.data_revision,
        "measurement_window": outcome.measurement_window,
        "expectation": outcome.expectation,
        "estimated_effect": outcome.estimated_effect,
        "study_run": outcome.study_run,
        "data_quality_caveats": outcome.data_quality_caveats,
        "review_verdict": outcome.review_verdict.value,
        "verdict_evidence": outcome.verdict_evidence,
    })
    amendments = rec.amendments + [
        DecisionAmendment(
            version=len(rec.amendments) + 1,
            author=author,
            reason=reason,
            scope="outcome_recorded",
            previous_version=len(rec.amendments),
            created_at=ts,
            changes={"old_status": rec.status.value, "new_status": "evaluated"},
        )
    ]
    amendments_json = json.dumps([
        {
            "version": a.version, "author": a.author, "reason": a.reason,
            "scope": a.scope, "previous_version": a.previous_version,
            "created_at": a.created_at, "changes": a.changes,
        }
        for a in amendments
    ])
    conn.execute(
        "UPDATE decision SET status='evaluated', outcome_json=?, amendments_json=?, updated_at=? WHERE tenant_id=? AND id=?",
        (outcome_json, amendments_json, ts, tenant_id, decision_id),
    )
    conn.commit()
    rec.status = DecisionStatus.EVALUATED
    rec.outcome = outcome
    rec.amendments = amendments
    rec.updated_at = ts
    return rec


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _row_to_record(row) -> DecisionRecord:
    brief_data = json.loads(row["brief_json"])
    brief = DecisionBrief(
        problem=brief_data["problem"],
        relevant_findings=brief_data.get("relevant_findings", []),
        proposed_action=brief_data.get("proposed_action", ""),
        baseline_option=brief_data.get("baseline_option", ""),
        scope=brief_data.get("scope", ""),
        owner=brief_data.get("owner", ""),
        trade_offs=brief_data.get("trade_offs", []),
        assumptions=brief_data.get("assumptions", []),
        evidence_coverage=brief_data.get("evidence_coverage", []),
        validation_plan=brief_data.get("validation_plan", ""),
        counter_metrics=brief_data.get("counter_metrics", []),
        expected_effect=brief_data.get("expected_effect", "unknown"),
    )
    ce_data = json.loads(row["counterevidence_json"] or "[]")
    counterevidence = [
        CounterevidenceCheck(
            hypothesis=c["hypothesis"],
            state=CounterevidenceState(c["state"]),
            detail=c.get("detail"),
        )
        for c in ce_data
    ]
    amd_data = json.loads(row["amendments_json"] or "[]")
    amendments = [
        DecisionAmendment(
            version=a["version"], author=a["author"], reason=a["reason"],
            scope=a["scope"], previous_version=a.get("previous_version", 0),
            created_at=a["created_at"], changes=a.get("changes"),
        )
        for a in amd_data
    ]
    outcome = None
    if row["outcome_json"]:
        od = json.loads(row["outcome_json"])
        outcome = OutcomeRecord(
            observed_results=od.get("observed_results", {}),
            pinned_definition_version=od.get("pinned_definition_version"),
            data_revision=od.get("data_revision"),
            measurement_window=od.get("measurement_window", ""),
            expectation=od.get("expectation", ""),
            estimated_effect=od.get("estimated_effect"),
            study_run=od.get("study_run"),
            data_quality_caveats=od.get("data_quality_caveats", []),
            review_verdict=Verdict(od["review_verdict"]),
            verdict_evidence=od.get("verdict_evidence", ""),
        )
    return DecisionRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        title=row["title"],
        status=DecisionStatus(row["status"]),
        brief=brief,
        counterevidence=counterevidence,
        amendments=amendments,
        outcome=outcome,
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )