"""End-to-end ingest pipeline: scan -> parse -> stage revision -> validate -> publish.

Atomic publication per spec §8.5: attempt objects are written to private
immutable paths; the published pointer moves in one transaction with an outbox
event. Failed attempts are never visible to query execution.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import polars as pl

from .grain import grain_candidates
from .objectstore import LocalObjectStore
from .parsing import ParseOutcome, parse_csv
from .scanning import formula_risk_cells, scan
from .store import Store, new_id, now_iso


class LeaseExpired(Exception):
    pass


def process_upload(store: Store, objects: LocalObjectStore, tenant_id: str, upload_id: str, lease_owner: str = "worker-1", lease_seconds: int = 300) -> dict:
    """Runs the bounded pipeline for one upload. Returns preview summary."""
    row = store.conn.execute(
        "SELECT * FROM upload WHERE tenant_id=? AND id=?", (tenant_id, upload_id)
    ).fetchone()
    if row is None:
        raise LookupError("upload not found")

    data = objects.get_quarantine(row["quarantine_key"])
    verdict = scan(row["filename"], data)
    if verdict.verdict == "rejected":
        store.conn.execute("UPDATE upload SET status='rejected', scan_result=? WHERE tenant_id=? AND id=?",
                           (json.dumps({"verdict": "rejected", "reasons": verdict.reasons}), tenant_id, upload_id))
        store.conn.commit()
        store.audit(tenant_id, "worker", "upload.scan", upload_id, "rejected", {"reasons": verdict.reasons})
        return {"status": "rejected", "reasons": verdict.reasons}

    outcome: ParseOutcome = parse_csv(data)
    preview = {
        "upload_id": upload_id,
        "detected": {
            "delimiter": outcome.detected_delimiter,
            "encoding": outcome.detected_encoding,
            "header_row": outcome.header_row,
            "dialect_confidence": outcome.dialect_confidence,
        },
        "columns": outcome.columns,
        "row_count": outcome.row_count,
        "rejected_rows": outcome.rejected_rows,
        "issues": outcome.issues + [f"formula-injection candidates: {f}" for f in formula_risk_cells(data.decode(outcome.detected_encoding, errors="replace"))[:5]],
    }

    raw_key = objects.retain_raw(row["quarantine_key"])
    preview["raw_retention_key"] = raw_key

    dataset_id = row["dataset_id"]
    if dataset_id is None:
        dataset_id = new_id()
        store.conn.execute(
            "INSERT INTO dataset(tenant_id, id, workspace_id, name, created_at) VALUES (?,?,?,?,?)",
            (tenant_id, dataset_id, row["workspace_id"], row["filename"], now_iso()),
        )
        store.conn.execute("UPDATE upload SET dataset_id=? WHERE tenant_id=? AND id=?", (dataset_id, tenant_id, upload_id))

    cur = store.conn.execute(
        "SELECT COALESCE(MAX(revision),0)+1 AS next FROM dataset_revision WHERE tenant_id=? AND dataset_id=?",
        (tenant_id, dataset_id),
    ).fetchone()
    revision = cur["next"]

    import io
    buf = io.BytesIO()
    outcome.frame.write_parquet(buf)
    parquet_bytes = buf.getvalue()
    obj = objects.put_revision_object(tenant_id, dataset_id, revision, "data.parquet", parquet_bytes)
    manifest = {
        "objects": [obj],
        "schema": {c["name"]: c["inferred_type"] for c in outcome.columns},
        "row_count": outcome.row_count,
        "rejected_row_count": len(outcome.rejected_rows),
        "transform_version": "identity@1.0",
        "checkpoint": {"source": f"upload:{upload_id}", "sha256": row["sha256"]},
    }

    lease = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
    store.conn.execute(
        "INSERT INTO dataset_revision(tenant_id, dataset_id, revision, state, manifest, row_count, rejected_row_count, lease_owner, lease_expires_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (tenant_id, dataset_id, revision, "validating", json.dumps(manifest), outcome.row_count, len(outcome.rejected_rows), lease_owner, lease, now_iso()),
    )
    store.conn.commit()

    candidates = grain_candidates(outcome.frame)
    # Revision state reflects parse/reconciliation success only.
    # Grain is a separate human confirmation gate enforced at publish (§9.2).
    new_state = "validated"
    store.conn.execute("UPDATE dataset_revision SET state=? WHERE tenant_id=? AND dataset_id=? AND revision=?",
                       (new_state, tenant_id, dataset_id, revision))
    store.conn.execute("UPDATE upload SET status='parsed', scan_result=?, parse_preview=? WHERE tenant_id=? AND id=?",
                       (json.dumps({"verdict": "clean", "reasons": []}), json.dumps(preview, default=str), tenant_id, upload_id))
    store.conn.commit()
    store.audit(tenant_id, "worker", "upload.parse", upload_id, new_state, {"revision": revision, "rejected_rows": len(outcome.rejected_rows)})

    return {"status": "parsed", "dataset_id": dataset_id, "revision": revision, "revision_state": new_state, "preview": preview, "grain_candidates": candidates}


def publish_revision(store: Store, tenant_id: str, dataset_id: str, revision: int, actor: str) -> dict:
    """One transaction: pointer move + outbox event (optimistic on current pointer)."""
    ds = store.conn.execute("SELECT * FROM dataset WHERE tenant_id=? AND id=?", (tenant_id, dataset_id)).fetchone()
    if ds is None:
        raise LookupError("dataset not found")
    if ds["grain_confirmed_at"] is None:
        raise PermissionError("grain_unconfirmed")
    rev = store.conn.execute(
        "SELECT * FROM dataset_revision WHERE tenant_id=? AND dataset_id=? AND revision=?",
        (tenant_id, dataset_id, revision),
    ).fetchone()
    if rev is None or rev["state"] != "validated":
        raise RuntimeError("revision_not_publishable")
    if ds["published_revision"] is not None and ds["published_revision"] >= revision:
        raise RuntimeError("concurrent_publish_conflict")

    with store.conn:
        cur = store.conn.execute(
            "UPDATE dataset SET published_revision=? WHERE tenant_id=? AND id=? AND (published_revision IS NULL OR published_revision < ?)",
            (revision, tenant_id, dataset_id, revision),
        )
        if cur.rowcount != 1:
            raise RuntimeError("concurrent_publish_conflict")
        store.conn.execute("UPDATE dataset_revision SET state='published', lease_owner=NULL, lease_expires_at=NULL WHERE tenant_id=? AND dataset_id=? AND revision=?",
                           (tenant_id, dataset_id, revision))
        store.emit(tenant_id, "dataset.revision_published", dataset_id, revision, {"revision_id": str(revision), "previous_revision_id": ds["published_revision"]})
    store.conn.commit()
    store.audit(tenant_id, actor, "dataset.publish", dataset_id, "success", {"revision": revision})
    return {"dataset_id": dataset_id, "published_revision": revision, "status": "published"}


def sweep_expired_leases(store: Store, now: datetime | None = None) -> int:
    """Independent lease sweeper: workers can die before finally (§8.5)."""
    now = (now or datetime.now(timezone.utc)).isoformat()
    with store.conn:
        cur = store.conn.execute(
            "UPDATE dataset_revision SET state='failed', lease_owner=NULL WHERE state='validating' AND lease_expires_at < ?",
            (now,),
        )
    return cur.rowcount
