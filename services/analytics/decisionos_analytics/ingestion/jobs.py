"""DB-backed ingestion jobs.

A run is claimed with a single conditional UPDATE (never executed twice), reads
from a connector in a bounded batch, then reuses the exact CSV upload pipeline:
object store -> parse -> grain candidates -> dataset revision -> publish. Only a
successful run advances the job watermark.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
from datetime import date, datetime
from typing import Any

from ..connectors import ConnectorError, get_connector
from ..objectstore import LocalObjectStore
from ..parsing import ParseError
from ..pipeline import process_upload, publish_revision
from ..profiling.quality import evaluate_rules, profile_dataset
from ..store import Store, new_id, now_iso

DEFAULT_MAX_ROWS = 50_000
DEFAULT_WORKSPACE = "ws-support-ops"
_logger = logging.getLogger("decisionos.ingest")


class JobError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        self.status = status
        self.code = code
        self.detail = detail
        super().__init__(detail)


class IngestionFailure(Exception):
    """Internal failure whose message is safe to persist on the run."""


def _objects_for(store: Store) -> LocalObjectStore:
    from pathlib import Path

    return LocalObjectStore(Path(store.path).resolve().parent / "objects")


def _job_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "data_source_id": row["data_source_id"],
        "name": row["name"],
        "target_table": row["target_table"],
        "mode": row["mode"],
        "watermark_column": row["watermark_column"],
        "watermark_value": row["watermark_value"],
        "schedule_cron": row["schedule_cron"],
        "max_rows": row["max_rows"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _run_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "rows_read": row["rows_read"],
        "rows_written": row["rows_written"],
        "dataset_id": row["dataset_id"],
        "upload_id": row["upload_id"],
        "error": row["error"],
        "stats": json.loads(row["stats_json"] or "{}"),
        "created_at": row["created_at"],
    }


def create_job(
    store: Store,
    tenant: str,
    data_source_id: str,
    name: str,
    target_table: str,
    mode: str = "full",
    watermark_column: str | None = None,
    watermark_value: str | None = None,
    schedule_cron: str | None = None,
    max_rows: int | None = None,
) -> dict:
    if not isinstance(name, str) or not name.strip():
        raise JobError(422, "missing_field", "Field 'name' is required.")
    if not isinstance(target_table, str) or not target_table.strip():
        raise JobError(422, "missing_field", "Field 'target_table' is required.")
    if mode not in ("full", "incremental"):
        raise JobError(422, "invalid_value", "Field 'mode' must be 'full' or 'incremental'.")
    if mode == "incremental" and (not watermark_column or watermark_value is None):
        raise JobError(
            422,
            "watermark_required",
            "Incremental jobs require 'watermark_column' and 'watermark_value'.",
        )
    if max_rows is not None:
        try:
            max_rows = int(max_rows)
        except (TypeError, ValueError) as exc:
            raise JobError(422, "invalid_value", "Field 'max_rows' must be an integer.") from exc
        if max_rows < 1:
            raise JobError(422, "invalid_value", "Field 'max_rows' must be positive.")
    source = store.conn.execute(
        "SELECT id FROM data_source WHERE tenant_id=? AND id=?", (tenant, data_source_id)
    ).fetchone()
    if source is None:
        raise JobError(404, "not_found", "Data source not found.")

    job_id = f"job-{new_id()[:12]}"
    timestamp = now_iso()
    store.execute_with_retry(
        """INSERT INTO ingest_job(
            tenant_id, id, data_source_id, name, target_table, mode, watermark_column,
            watermark_value, schedule_cron, max_rows, status, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            tenant,
            job_id,
            data_source_id,
            name.strip(),
            target_table.strip(),
            mode,
            watermark_column,
            None if watermark_value is None else str(watermark_value),
            schedule_cron,
            max_rows,
            "active",
            timestamp,
            timestamp,
        ),
    )
    store.audit(tenant, "api", "ingest.job.create", job_id, "success", {"mode": mode})
    return get_job(store, tenant, job_id)


def _job_row(store: Store, tenant: str, job_id: str) -> Any:
    return store.conn.execute(
        "SELECT * FROM ingest_job WHERE tenant_id=? AND id=?", (tenant, job_id)
    ).fetchone()


def get_job(store: Store, tenant: str, job_id: str) -> dict:
    row = _job_row(store, tenant, job_id)
    if row is None:
        raise JobError(404, "not_found", "not found")
    return _job_dict(row)


def list_jobs(store: Store, tenant: str) -> list[dict]:
    rows = store.conn.execute(
        "SELECT * FROM ingest_job WHERE tenant_id=? ORDER BY created_at DESC", (tenant,)
    ).fetchall()
    return [_job_dict(row) for row in rows]


def enqueue_run(store: Store, tenant: str, job_id: str | None = None) -> dict:
    # ``enqueue_run(store, job_id)`` is supported for system callers; the job
    # lookup resolves the tenant, and every subsequent access is tenant-filtered.
    if job_id is None:
        lookup = store.conn.execute(
            "SELECT tenant_id FROM ingest_job WHERE id=?", (tenant,)
        ).fetchone()
        if lookup is None:
            raise JobError(404, "not_found", "not found")
        tenant, job_id = lookup["tenant_id"], tenant
    if _job_row(store, tenant, job_id) is None:
        raise JobError(404, "not_found", "not found")
    run_id = f"run-{new_id()[:12]}"
    timestamp = now_iso()
    store.execute_with_retry(
        """INSERT INTO ingest_run(
            tenant_id, id, job_id, status, rows_read, rows_written, stats_json, created_at
        ) VALUES (?,?,?,?,?,?,?,?)""",
        (tenant, run_id, job_id, "queued", 0, 0, "{}", timestamp),
    )
    return {"run_id": run_id, "status": "queued"}


def _run_row(store: Store, run_id: str) -> Any:
    return store.conn.execute("SELECT * FROM ingest_run WHERE id=?", (run_id,)).fetchone()


def list_runs(store: Store, tenant: str, job_id: str) -> list[dict]:
    if _job_row(store, tenant, job_id) is None:
        raise JobError(404, "not_found", "not found")
    rows = store.conn.execute(
        "SELECT * FROM ingest_run WHERE tenant_id=? AND job_id=? ORDER BY created_at DESC",
        (tenant, job_id),
    ).fetchall()
    return [_run_dict(row) for row in rows]


def run_pending(store: Store, limit: int = 1) -> int:
    rows = store.conn.execute(
        "SELECT id, tenant_id FROM ingest_run WHERE status='queued' ORDER BY created_at ASC LIMIT ?",
        (max(1, int(limit)),),
    ).fetchall()
    executed = 0
    for row in rows:
        if execute_run(store, row["id"], row["tenant_id"]):
            executed += 1
    return executed


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _rows_to_csv(header: list[str], rows: list[list[Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_csv_value(value) for value in row])
    return buffer.getvalue().encode("utf-8")


def _max_observed(header: list[str], rows: list[list[Any]], column: str) -> str | None:
    index = header.index(column)
    values = [row[index] for row in rows if index < len(row) and row[index] is not None]
    if not values:
        return None
    numeric: list[float] = []
    for value in values:
        try:
            numeric.append(float(value))
        except (TypeError, ValueError):
            numeric = []
            break
    if numeric:
        best = max(numeric)
        return str(int(best)) if best.is_integer() else str(best)
    return str(max(str(value) for value in values))


def _latest_dataset_for_job(store: Store, tenant: str, job_id: str) -> str | None:
    row = store.conn.execute(
        """SELECT dataset_id FROM ingest_run
           WHERE tenant_id=? AND job_id=? AND dataset_id IS NOT NULL
           ORDER BY created_at DESC LIMIT 1""",
        (tenant, job_id),
    ).fetchone()
    return row["dataset_id"] if row else None


def _write_upload(store: Store, objects: LocalObjectStore, tenant: str, job: dict, data: bytes) -> str:
    upload_id = new_id()
    filename = f"{job['name']}.csv"
    quarantine_key = f"{tenant}/{DEFAULT_WORKSPACE}/{upload_id}/{filename}"
    store.execute_with_retry(
        """INSERT INTO upload(
            tenant_id, id, workspace_id, created_by, filename, quarantine_key, status, created_at
        ) VALUES (?,?,?,?,?,?,?,?)""",
        (tenant, upload_id, DEFAULT_WORKSPACE, "worker", filename, quarantine_key, "initiated", now_iso()),
    )
    sha256 = objects.put_quarantine(quarantine_key, data)
    store.execute_with_retry(
        "UPDATE upload SET sha256=?, status='quarantined' WHERE tenant_id=? AND id=?",
        (sha256, tenant, upload_id),
    )
    existing_dataset = _latest_dataset_for_job(store, tenant, job["id"])
    if existing_dataset:
        store.execute_with_retry(
            "UPDATE upload SET dataset_id=? WHERE tenant_id=? AND id=?",
            (existing_dataset, tenant, upload_id),
        )
    return upload_id


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, ConnectorError | IngestionFailure | ParseError | JobError):
        return str(exc)
    return "Ingestion failed."


def execute_run(store: Store, run_id: str, tenant_id: str | None = None) -> bool:
    row = _run_row(store, run_id)
    if row is None:
        return False
    tenant = row["tenant_id"]
    if tenant_id is not None and tenant != tenant_id:
        return False

    claimed = store.conn.execute(
        "UPDATE ingest_run SET status='running', started_at=? WHERE id=? AND tenant_id=? AND status='queued'",
        (now_iso(), run_id, tenant),
    )
    store.conn.commit()
    if claimed.rowcount != 1:
        return False
    _logger.info(json.dumps({"event": "ingest.run.running", "run_id": run_id, "tenant_id": tenant}))

    stats: dict[str, float] = {}
    dataset_id: str | None = None
    upload_id: str | None = None
    stage = time.perf_counter()
    try:
        job_row = store.conn.execute(
            "SELECT * FROM ingest_job WHERE tenant_id=? AND id=?", (tenant, row["job_id"])
        ).fetchone()
        if job_row is None:
            raise IngestionFailure("Ingestion job not found.")
        job = _job_dict(job_row)
        source_row = store.conn.execute(
            "SELECT * FROM data_source WHERE tenant_id=? AND id=?", (tenant, job["data_source_id"])
        ).fetchone()
        if source_row is None:
            raise IngestionFailure("Data source not found.")
        connector = get_connector(source_row)

        limit = int(job["max_rows"] or DEFAULT_MAX_ROWS)
        is_incremental = job["mode"] == "incremental"
        watermark_column = job["watermark_column"] if is_incremental else None
        watermark_value = job["watermark_value"] if is_incremental else None

        stage = time.perf_counter()
        read_kwargs: dict[str, Any] = {"columns": None, "limit": limit, "offset": 0}
        if is_incremental:
            read_kwargs["watermark_column"] = watermark_column
            read_kwargs["watermark_value"] = watermark_value
        header, rows = connector.read_rows(job["target_table"], **read_kwargs)
        stats["read_ms"] = round((time.perf_counter() - stage) * 1000, 3)
        if not header:
            raise IngestionFailure("The source returned no columns.")
        if watermark_column and watermark_column not in header:
            raise IngestionFailure(
                f"Watermark column '{watermark_column}' was not returned by the source."
            )

        stage = time.perf_counter()
        objects = _objects_for(store)
        upload_id = _write_upload(store, objects, tenant, job, _rows_to_csv(header, rows))
        stats["write_object_ms"] = round((time.perf_counter() - stage) * 1000, 3)

        stage = time.perf_counter()
        outcome = process_upload(store, objects, tenant, upload_id, lease_owner="ingest-worker")
        stats["parse_ms"] = round((time.perf_counter() - stage) * 1000, 3)
        if outcome.get("status") == "rejected":
            raise IngestionFailure("The ingested file was rejected by the safety scan.")
        dataset_id = outcome["dataset_id"]
        store.execute_with_retry(
            "UPDATE ingest_run SET dataset_id=?, upload_id=? WHERE tenant_id=? AND id=?",
            (dataset_id, upload_id, tenant, run_id),
        )
        revision = int(outcome["revision"])
        rows_written = int(outcome["preview"]["row_count"])

        stage = time.perf_counter()
        candidates = outcome.get("grain_candidates") or []
        unique = [candidate for candidate in candidates if candidate.get("unique_over_full_data")]
        if not unique:
            raise IngestionFailure("No unique grain candidate was found, so the dataset cannot be published.")
        unique.sort(key=lambda candidate: (len(candidate["key_columns"]), candidate["key_columns"]))
        dataset = store.conn.execute(
            "SELECT grain_confirmed_at FROM dataset WHERE tenant_id=? AND id=?", (tenant, dataset_id)
        ).fetchone()
        if dataset is not None and dataset["grain_confirmed_at"] is None:
            store.execute_with_retry(
                "UPDATE dataset SET grain_confirmed_at=?, grain_key=? WHERE tenant_id=? AND id=?",
                (now_iso(), json.dumps(unique[0]["key_columns"]), tenant, dataset_id),
            )
        published = publish_revision(store, tenant, dataset_id, revision, "ingest-worker")
        stats["publish_ms"] = round((time.perf_counter() - stage) * 1000, 3)

        stage = time.perf_counter()
        profile_dataset(store, dataset_id, revision, tenant_id=tenant)
        stats["profile_ms"] = round((time.perf_counter() - stage) * 1000, 3)

        stage = time.perf_counter()
        evaluate_rules(store, dataset_id, run_id=run_id, tenant_id=tenant, revision=revision)
        stats["quality_ms"] = round((time.perf_counter() - stage) * 1000, 3)

        watermark = None
        if is_incremental and watermark_column and rows:
            watermark = _max_observed(header, rows, watermark_column)

        finished = now_iso()
        with store.conn:
            store.conn.execute(
                """UPDATE ingest_run SET status='succeeded', finished_at=?, rows_read=?,
                   rows_written=?, dataset_id=?, upload_id=?, error=NULL, stats_json=?
                   WHERE tenant_id=? AND id=?""",
                (
                    finished,
                    len(rows),
                    rows_written,
                    dataset_id,
                    upload_id,
                    json.dumps(stats),
                    tenant,
                    run_id,
                ),
            )
            if watermark is not None:
                store.conn.execute(
                    "UPDATE ingest_job SET watermark_value=?, updated_at=? WHERE tenant_id=? AND id=?",
                    (watermark, finished, tenant, job["id"]),
                )
        store.audit(
            tenant, "worker", "ingest.run.succeeded", run_id, "success",
            {"job_id": job["id"], "dataset_id": dataset_id, "revision": published["published_revision"]},
        )
        _logger.info(
            json.dumps(
                {
                    "event": "ingest.run.succeeded",
                    "run_id": run_id,
                    "dataset_id": dataset_id,
                    "rows_written": rows_written,
                }
            )
        )
        return True
    except Exception as exc:  # noqa: BLE001 - every failure is recorded, never raised to the worker
        message = _safe_error(exc)
        with store.conn:
            store.conn.execute(
                """UPDATE ingest_run SET status='failed', finished_at=?, error=?, stats_json=?,
                   dataset_id=COALESCE(?, dataset_id), upload_id=COALESCE(?, upload_id)
                   WHERE tenant_id=? AND id=?""",
                (now_iso(), message, json.dumps(stats), dataset_id, upload_id, tenant, run_id),
            )
        store.audit(tenant, "worker", "ingest.run.failed", run_id, "failed", {"error": message})
        _logger.info(
            json.dumps({"event": "ingest.run.failed", "run_id": run_id, "error": message})
        )
        return True
