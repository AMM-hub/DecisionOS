"""D2 Immutable Evidence Snapshot Engine & Structured Facts (spec §10, §16).

Server-resolved provenance, deterministic canonical digests, logical immutability,
and structured analytical fact representation.
"""

from __future__ import annotations

import hashlib
import io
import json
from enum import Enum
from typing import Any

import polars as pl
from pydantic import BaseModel, Field

from .execution import compile_plan, execute
from .objectstore import LocalObjectStore
from .semantics import MetricDefinitionContent, MetricQueryRequest
from .store import Store, new_id, now_iso

# ---------------------------------------------------------------------------
# Enums matching spec vocabulary
# ---------------------------------------------------------------------------

class EvidenceType(str, Enum):
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    SIMULATED = "simulated"
    CAUSAL_ESTIMATE = "causal_estimate"
    HYPOTHESIS = "hypothesis"


class SupportStatus(str, Enum):
    SUPPORTING = "supporting"
    COUNTER = "counter"
    NEUTRAL = "neutral"
    UNVERIFIED = "unverified"


class ExactnessClass(str, Enum):
    EXACT = "exact"
    NUMERICALLY_EQUIVALENT = "numerically_equivalent"
    STOCHASTICALLY_REPRODUCIBLE = "stochastically_reproducible"
    PRESENTATION_REPRODUCIBLE = "presentation_reproducible"


class ReproducibilityStatus(str, Enum):
    REPRODUCIBLE = "reproducible"
    PARTIALLY_REPRODUCIBLE = "partially_reproducible"
    UNAVAILABLE_AFTER_ERASURE = "unavailable_after_erasure"


# ---------------------------------------------------------------------------
# Structured Fact Model
# ---------------------------------------------------------------------------

class StructuredFact(BaseModel):
    metric_id: str
    value: Any
    unit: str = "count"
    segment: dict[str, Any] = Field(default_factory=dict)
    period: str = ""
    comparison: str | None = None
    lineage: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Canonical Digest Computation
# ---------------------------------------------------------------------------

def compute_canonical_digest(data: list[dict] | dict) -> str:
    """Computes a deterministic SHA-256 digest over logical result content.
    Sorts dictionary keys and formats numbers deterministically to ensure
    identical logical results produce identical digests regardless of memory ordering.
    """
    canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Evidence Artifact Core Logic
# ---------------------------------------------------------------------------

MAX_UNSAMPLED_ROWS = 50000


class EvidenceError(Exception):
    """Domain exception for evidence engine failure."""
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def capture_evidence(
    store: Store,
    objects: LocalObjectStore,
    tenant_id: str,
    user_id: str,
    investigation_id: str,
    metric_defn: MetricDefinitionContent,
    query_req: MetricQueryRequest,
    dataset_frame: pl.DataFrame,
    dataset_revision: int,
    evidence_type: EvidenceType = EvidenceType.OBSERVED,
    support_status: SupportStatus = SupportStatus.SUPPORTING,
    parent_artifact_ids: list[str] | None = None,
    allow_sampling: bool = False,
) -> dict:
    # 1. Validate tenant ownership of investigation
    inv = store.conn.execute(
        "SELECT id FROM investigation WHERE tenant_id=? AND id=?",
        (tenant_id, investigation_id),
    ).fetchone()
    if inv is None:
        raise EvidenceError("investigation_not_found", "Investigation not found")

    # 2. Compile typed plan & execute over Polars
    plan = compile_plan(metric_defn, query_req, dataset_revision)
    rows, flags = execute(dataset_frame, metric_defn, query_req, plan)

    # 3. Check row limits & explicit sampling
    total_rows = len(rows)
    quality_flags = list(flags)
    if total_rows > MAX_UNSAMPLED_ROWS:
        if not allow_sampling:
            raise EvidenceError(
                "result_too_large",
                f"Result row count ({total_rows}) exceeds maximum allowed un-sampled limit ({MAX_UNSAMPLED_ROWS}). Filter or enable sampling.",
            )
        rows = rows[:MAX_UNSAMPLED_ROWS]
        quality_flags.append("sampled")

    # 4. Canonical digest calculation
    digest = compute_canonical_digest(rows)
    artifact_id = f"ev-{new_id()[:12]}"
    created_at = now_iso()

    # 5. Payload storage strategy (JSON vs Parquet in ObjectStore)
    storage_format = "json"
    payload_json = None
    parquet_key = None

    if total_rows <= 100:
        payload_json = json.dumps(rows)
    else:
        storage_format = "parquet"
        df_res = pl.DataFrame(rows)
        buf = io.BytesIO()
        df_res.write_parquet(buf)
        parquet_bytes = buf.getvalue()
        obj_meta = objects.put_evidence_object(tenant_id, artifact_id, parquet_bytes)
        parquet_key = obj_meta["key"]

    # 6. Persist immutable record in SQLite
    store.conn.execute(
        """INSERT INTO evidence_artifact(
            tenant_id, id, investigation_id, parent_artifact_ids_json, evidence_type, support_status,
            quality_flags_json, metric_id, definition_version, dataset_id, dataset_revision,
            resolved_plan_json, query_params_json, canonical_digest, storage_format, payload_json,
            parquet_key, row_count, exactness_class, reproducibility_status, created_by, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            tenant_id,
            artifact_id,
            investigation_id,
            json.dumps(parent_artifact_ids or []),
            evidence_type.value,
            support_status.value,
            json.dumps(quality_flags),
            metric_defn.metric_id,
            1,
            metric_defn.dataset_id,
            dataset_revision,
            json.dumps(plan),
            json.dumps(query_req.model_dump()),
            digest,
            storage_format,
            payload_json,
            parquet_key,
            total_rows,
            ExactnessClass.EXACT.value,
            ReproducibilityStatus.REPRODUCIBLE.value,
            user_id,
            created_at,
        ),
    )
    store.conn.commit()

    store.audit(
        tenant_id, user_id, "evidence.capture", artifact_id, "success",
        {"metric_id": metric_defn.metric_id, "digest": digest, "row_count": total_rows}
    )

    return get_evidence(store, objects, tenant_id, artifact_id)


def get_evidence(
    store: Store,
    objects: LocalObjectStore,
    tenant_id: str,
    artifact_id: str,
) -> dict:
    row = store.conn.execute(
        "SELECT * FROM evidence_artifact WHERE tenant_id=? AND id=?",
        (tenant_id, artifact_id),
    ).fetchone()
    if row is None:
        raise EvidenceError("evidence_not_found", "Evidence artifact not found")

    rec = dict(row)
    # Parse JSON fields
    parent_ids = json.loads(rec["parent_artifact_ids_json"])
    quality_flags = json.loads(rec["quality_flags_json"])
    resolved_plan = json.loads(rec["resolved_plan_json"])
    query_params = json.loads(rec["query_params_json"])

    # Load result payload based on storage_format
    if rec["storage_format"] == "json":
        rows = json.loads(rec["payload_json"]) if rec["payload_json"] else []
    else:
        parquet_bytes = objects.get_evidence_object(rec["parquet_key"])
        df_res = pl.read_parquet(io.BytesIO(parquet_bytes))
        rows = df_res.to_dicts()

    # Re-verify canonical digest on retrieval
    current_digest = compute_canonical_digest(rows)
    if current_digest != rec["canonical_digest"]:
        raise EvidenceError("integrity_mismatch", "Evidence payload failed canonical digest verification (tamper detected)")

    return {
        "artifact_id": rec["id"],
        "tenant_id": rec["tenant_id"],
        "investigation_id": rec["investigation_id"],
        "parent_artifact_ids": parent_ids,
        "evidence_type": rec["evidence_type"],
        "support_status": rec["support_status"],
        "quality_flags": quality_flags,
        "metric_id": rec["metric_id"],
        "definition_version": rec["definition_version"],
        "dataset_id": rec["dataset_id"],
        "dataset_revision": rec["dataset_revision"],
        "resolved_plan": resolved_plan,
        "query_params": query_params,
        "canonical_digest": rec["canonical_digest"],
        "digest_verified": True,
        "storage_format": rec["storage_format"],
        "row_count": rec["row_count"],
        "exactness_class": rec["exactness_class"],
        "reproducibility_status": rec["reproducibility_status"],
        "created_by": rec["created_by"],
        "created_at": rec["created_at"],
        "results": rows,
    }
