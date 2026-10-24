"""Saved analysis artifacts: an immutable query plus its latest result provenance."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .analytics.query import AnalyticsQuery, resolve_revision, run_query
from .objectstore import LocalObjectStore
from .store import Store, new_id, now_iso


class ArtifactError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        self.status = status
        self.code = code
        self.detail = detail
        super().__init__(detail)


def _artifact_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "dataset_id": row["dataset_id"],
        "revision": row["revision"],
        "query": json.loads(row["query_json"]),
        "result_digest": row["result_digest"],
        "row_count": row["row_count"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _fetch(store: Store, tenant: str, artifact_id: str) -> sqlite3.Row | None:
    return store.conn.execute(
        "SELECT * FROM analysis_artifact WHERE tenant_id=? AND id=?", (tenant, artifact_id)
    ).fetchone()


def get_artifact(store: Store, tenant: str, artifact_id: str) -> dict[str, Any]:
    row = _fetch(store, tenant, artifact_id)
    if row is None:
        raise ArtifactError(404, "not_found", "not found")
    return _artifact_dict(row)


def list_artifacts(
    store: Store, tenant: str, limit: int, offset: int, q: str | None
) -> tuple[int, list[dict[str, Any]]]:
    where = "WHERE tenant_id=?"
    params: list[Any] = [tenant]
    if q:
        where += " AND LOWER(name) LIKE ?"
        params.append(f"%{q.lower()}%")
    total = store.conn.execute(
        f"SELECT COUNT(*) c FROM analysis_artifact {where}", tuple(params)
    ).fetchone()["c"]
    rows = store.conn.execute(
        f"SELECT * FROM analysis_artifact {where} ORDER BY updated_at DESC, name ASC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return int(total), [_artifact_dict(row) for row in rows]


def create_artifact(
    store: Store,
    objects: LocalObjectStore,
    tenant: str,
    user: str,
    name: str,
    query: AnalyticsQuery,
    run_now: bool,
) -> dict[str, Any]:
    clean_name = (name or "").strip()
    if not clean_name:
        raise ArtifactError(422, "missing_field", "Field 'name' is required.")
    resolved = resolve_revision(store, tenant, query)

    result = None
    if run_now:
        result = run_query(store, objects, tenant, user, query)

    artifact_id = f"ana-{new_id()[:12]}"
    timestamp = now_iso()
    try:
        store.conn.execute(
            """INSERT INTO analysis_artifact(
                tenant_id, id, name, dataset_id, revision, query_json,
                result_digest, row_count, created_by, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                tenant,
                artifact_id,
                clean_name,
                query.dataset_id,
                result.revision if result else resolved.revision,
                json.dumps(query.model_dump()),
                result.result_digest if result else None,
                result.row_count if result else 0,
                user,
                timestamp,
                timestamp,
            ),
        )
        store.conn.commit()
    except sqlite3.IntegrityError as exc:
        store.conn.rollback()
        raise ArtifactError(409, "duplicate_analysis_name", f"An analysis named '{clean_name}' already exists.") from exc

    store.audit(tenant, user, "analytics.analysis.create", artifact_id, "success", {"name": clean_name})
    artifact = get_artifact(store, tenant, artifact_id)
    if result is not None:
        artifact["last_result"] = result.as_dict()
    return artifact


def rerun_artifact(
    store: Store, objects: LocalObjectStore, tenant: str, user: str, artifact_id: str
) -> dict[str, Any]:
    row = _fetch(store, tenant, artifact_id)
    if row is None:
        raise ArtifactError(404, "not_found", "not found")
    query = AnalyticsQuery.model_validate(json.loads(row["query_json"]))
    result = run_query(store, objects, tenant, user, query)
    store.conn.execute(
        """UPDATE analysis_artifact
           SET revision=?, result_digest=?, row_count=?, updated_at=?
           WHERE tenant_id=? AND id=?""",
        (result.revision, result.result_digest, result.row_count, now_iso(), tenant, artifact_id),
    )
    store.conn.commit()
    store.audit(tenant, user, "analytics.analysis.run", artifact_id, "success", {"evidence_ref": result.evidence_ref})
    artifact = get_artifact(store, tenant, artifact_id)
    artifact["last_result"] = result.as_dict()
    return artifact


def update_artifact(
    store: Store,
    objects: LocalObjectStore,
    tenant: str,
    user: str,
    artifact_id: str,
    name: str | None,
    query: AnalyticsQuery | None,
    run_now: bool,
) -> dict[str, Any]:
    row = _fetch(store, tenant, artifact_id)
    if row is None:
        raise ArtifactError(404, "not_found", "not found")

    new_name = row["name"]
    if name is not None:
        new_name = name.strip()
        if not new_name:
            raise ArtifactError(422, "missing_field", "Field 'name' is required.")

    new_query = query or AnalyticsQuery.model_validate(json.loads(row["query_json"]))
    resolved = resolve_revision(store, tenant, new_query)

    result = None
    if run_now:
        result = run_query(store, objects, tenant, user, new_query)

    try:
        store.conn.execute(
            """UPDATE analysis_artifact
               SET name=?, dataset_id=?, revision=?, query_json=?, result_digest=?, row_count=?, updated_at=?
               WHERE tenant_id=? AND id=?""",
            (
                new_name,
                new_query.dataset_id,
                result.revision if result else resolved.revision,
                json.dumps(new_query.model_dump()),
                result.result_digest if result else row["result_digest"],
                result.row_count if result else row["row_count"],
                now_iso(),
                tenant,
                artifact_id,
            ),
        )
        store.conn.commit()
    except sqlite3.IntegrityError as exc:
        store.conn.rollback()
        raise ArtifactError(409, "duplicate_analysis_name", f"An analysis named '{new_name}' already exists.") from exc

    store.audit(tenant, user, "analytics.analysis.update", artifact_id, "success", {"name": new_name})
    artifact = get_artifact(store, tenant, artifact_id)
    if result is not None:
        artifact["last_result"] = result.as_dict()
    return artifact


def delete_artifact(store: Store, tenant: str, user: str, artifact_id: str) -> None:
    row = _fetch(store, tenant, artifact_id)
    if row is None:
        raise ArtifactError(404, "not_found", "not found")
    store.conn.execute(
        "DELETE FROM analysis_artifact WHERE tenant_id=? AND id=?", (tenant, artifact_id)
    )
    store.conn.commit()
    store.audit(tenant, user, "analytics.analysis.delete", artifact_id, "success", {"name": row["name"]})
