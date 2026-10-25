"""Exact profiling and data-quality evaluation over published revisions.

Nothing here samples or estimates. Every null count, distinct count, minimum and
maximum is computed from the published revision's stored Parquet data.
"""

from __future__ import annotations

import io
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from ..objectstore import LocalObjectStore
from ..store import Store, new_id, now_iso

RULE_KINDS = ("not_null", "unique", "range", "regex")
SEVERITIES = ("error", "warn", "info")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ].*)?$")


class QualityError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        self.status = status
        self.code = code
        self.detail = detail
        super().__init__(detail)


def _tenant_for_dataset(store: Store, dataset_id: str, tenant_id: str | None) -> str:
    if tenant_id:
        row = store.conn.execute(
            "SELECT tenant_id FROM dataset WHERE tenant_id=? AND id=?", (tenant_id, dataset_id)
        ).fetchone()
        if row is None:
            raise QualityError(404, "not_found", "not found")
        return tenant_id
    row = store.conn.execute("SELECT tenant_id FROM dataset WHERE id=?", (dataset_id,)).fetchone()
    if row is None:
        raise QualityError(404, "not_found", "not found")
    return str(row["tenant_id"])


def _revision_for(store: Store, tenant: str, dataset_id: str, revision: int | None) -> int:
    if revision is not None:
        row = store.conn.execute(
            "SELECT revision FROM dataset_revision WHERE tenant_id=? AND dataset_id=? AND revision=?",
            (tenant, dataset_id, revision),
        ).fetchone()
        if row is None:
            raise QualityError(404, "not_found", "Dataset revision not found.")
        return int(revision)
    dataset = store.conn.execute(
        "SELECT published_revision FROM dataset WHERE tenant_id=? AND id=?", (tenant, dataset_id)
    ).fetchone()
    if dataset is None:
        raise QualityError(404, "not_found", "not found")
    if dataset["published_revision"] is None:
        raise QualityError(409, "no_published_revision", "No published revision exists for this dataset.")
    return int(dataset["published_revision"])


def _manifest(store: Store, tenant: str, dataset_id: str, revision: int) -> dict:
    row = store.conn.execute(
        "SELECT manifest FROM dataset_revision WHERE tenant_id=? AND dataset_id=? AND revision=?",
        (tenant, dataset_id, revision),
    ).fetchone()
    if row is None:
        raise QualityError(404, "not_found", "Dataset revision not found.")
    return json.loads(row["manifest"])


def _objects_for(store: Store) -> LocalObjectStore:
    return LocalObjectStore(Path(store.path).resolve().parent / "objects")


def load_frame(store: Store, tenant: str, dataset_id: str, revision: int) -> pl.DataFrame:
    manifest = _manifest(store, tenant, dataset_id, revision)
    objects = _objects_for(store)
    return pl.read_parquet(io.BytesIO(objects.get_revision_object(manifest["objects"][0]["key"])))


def _dtype_name(dtype: pl.DataType) -> str:
    if dtype in (pl.Int8, pl.Int16, pl.Int32, pl.Int64, pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64):
        return "integer"
    if dtype in (pl.Float32, pl.Float64):
        return "float"
    if dtype == pl.Boolean:
        return "boolean"
    if dtype == pl.Date:
        return "date"
    if isinstance(dtype, pl.Datetime):
        return "datetime"
    if dtype == pl.Utf8:
        return "string"
    return str(dtype)


def _string_nulls(column: pl.Series) -> int:
    if column.dtype == pl.Utf8:
        return int(column.is_null().sum() + (column == "").sum())
    return int(column.is_null().sum())


def _non_null_values(column: pl.Series) -> list[Any]:
    if column.dtype == pl.Utf8:
        return [value for value in column.to_list() if value is not None and value != ""]
    return [value for value in column.drop_nulls().to_list() if value is not None]


def _looks_like_dates(values: list[Any]) -> bool:
    if not values:
        return False
    return all(isinstance(value, str) and _ISO_DATE.match(value) for value in values)


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _profile_column(frame: pl.DataFrame, name: str) -> dict[str, Any]:
    column = frame[name]
    row_count = frame.height
    null_count = _string_nulls(column)
    values = _non_null_values(column)
    dtype_name = _dtype_name(column.dtype)
    distinct_count = len(set(values))
    min_value = None
    max_value = None
    if values and dtype_name in ("integer", "float"):
        min_value = min(values)
        max_value = max(values)
    elif values and (dtype_name in ("date", "datetime") or _looks_like_dates(values)):
        comparable = [str(value) for value in values]
        min_value = min(comparable)
        max_value = max(comparable)
    return {
        "column_name": name,
        "dtype": dtype_name,
        "row_count": row_count,
        "null_count": null_count,
        "null_rate": round(null_count / row_count, 4) if row_count else 0.0,
        "distinct_count": distinct_count,
        "min_value": _json_value(min_value),
        "max_value": _json_value(max_value),
    }


def profile_dataset(
    store: Store,
    dataset_id: str,
    revision: int | None = None,
    tenant_id: str | None = None,
) -> list[dict]:
    tenant = _tenant_for_dataset(store, dataset_id, tenant_id)
    resolved_revision = _revision_for(store, tenant, dataset_id, revision)
    frame = load_frame(store, tenant, dataset_id, resolved_revision)
    profiles = [_profile_column(frame, name) for name in frame.columns]

    with store.conn:
        store.conn.execute(
            "DELETE FROM data_profile WHERE tenant_id=? AND dataset_id=? AND revision=?",
            (tenant, dataset_id, resolved_revision),
        )
        timestamp = now_iso()
        for profile in profiles:
            store.conn.execute(
                """INSERT INTO data_profile(
                    tenant_id, id, dataset_id, revision, column_name, dtype, row_count,
                    null_count, null_rate, distinct_count, min_value, max_value, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    tenant,
                    new_id(),
                    dataset_id,
                    resolved_revision,
                    profile["column_name"],
                    profile["dtype"],
                    profile["row_count"],
                    profile["null_count"],
                    profile["null_rate"],
                    profile["distinct_count"],
                    None if profile["min_value"] is None else str(profile["min_value"]),
                    None if profile["max_value"] is None else str(profile["max_value"]),
                    timestamp,
                ),
            )
    store.audit(
        tenant, "worker", "dataset.profile", dataset_id, "success",
        {"revision": resolved_revision, "columns": len(profiles)},
    )
    return profiles


def _rule_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "dataset_id": row["dataset_id"],
        "column_name": row["column_name"],
        "kind": row["kind"],
        "params": json.loads(row["params_json"] or "{}"),
        "severity": row["severity"],
        "created_at": row["created_at"],
    }


def _validate_params(kind: str, params: Any) -> dict:
    if not isinstance(params, dict):
        raise QualityError(422, "invalid_value", "Field 'params' must be an object.")
    if kind == "range":
        minimum = params.get("min")
        maximum = params.get("max")
        if minimum is None and maximum is None:
            raise QualityError(422, "missing_field", "Range rules require 'min' and/or 'max'.")
        for label, value in (("min", minimum), ("max", maximum)):
            if value is not None and not isinstance(value, (int, float)):
                raise QualityError(422, "invalid_value", f"Range '{label}' must be a number.")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise QualityError(422, "invalid_value", "Range 'min' must not exceed 'max'.")
        return {"min": minimum, "max": maximum}
    if kind == "regex":
        pattern = params.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise QualityError(422, "missing_field", "Regex rules require a 'pattern' string.")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise QualityError(422, "invalid_value", "Regex pattern is invalid.") from exc
        return {"pattern": pattern}
    return {}


def create_rule(
    store: Store,
    tenant: str,
    dataset_id: str,
    column_name: str,
    kind: str,
    params: Any = None,
    severity: str = "error",
) -> dict:
    if not isinstance(column_name, str) or not column_name.strip():
        raise QualityError(422, "missing_field", "Field 'column_name' is required.")
    if kind not in RULE_KINDS:
        raise QualityError(422, "unsupported_rule_kind", f"Unsupported quality rule kind '{kind}'.")
    if severity not in SEVERITIES:
        raise QualityError(422, "invalid_value", f"Unsupported severity '{severity}'.")
    if _tenant_for_dataset(store, dataset_id, tenant) != tenant:
        raise QualityError(404, "not_found", "not found")
    clean_params = _validate_params(kind, params or {})

    latest = store.conn.execute(
        "SELECT manifest FROM dataset_revision WHERE tenant_id=? AND dataset_id=? ORDER BY revision DESC LIMIT 1",
        (tenant, dataset_id),
    ).fetchone()
    if latest is None:
        raise QualityError(409, "no_dataset_revision", "No dataset revision exists yet.")
    schema = json.loads(latest["manifest"]).get("schema") or {}
    if column_name not in schema:
        raise QualityError(422, "unknown_column", f"Unknown column '{column_name}' for this dataset.")

    rule_id = f"qr-{new_id()[:12]}"
    store.execute_with_retry(
        """INSERT INTO quality_rule(
            tenant_id, id, dataset_id, column_name, kind, params_json, severity, created_at
        ) VALUES (?,?,?,?,?,?,?,?)""",
        (tenant, rule_id, dataset_id, column_name, kind, json.dumps(clean_params), severity, now_iso()),
    )
    store.audit(tenant, "api", "quality.rule.create", rule_id, "success", {"kind": kind})
    row = store.conn.execute(
        "SELECT * FROM quality_rule WHERE tenant_id=? AND id=?", (tenant, rule_id)
    ).fetchone()
    return _rule_dict(row)


def list_rules(store: Store, tenant: str, dataset_id: str) -> list[dict]:
    _tenant_for_dataset(store, dataset_id, tenant)
    rows = store.conn.execute(
        "SELECT * FROM quality_rule WHERE tenant_id=? AND dataset_id=? ORDER BY created_at ASC",
        (tenant, dataset_id),
    ).fetchall()
    return [_rule_dict(row) for row in rows]


def delete_rule(store: Store, tenant: str, dataset_id: str, rule_id: str) -> None:
    row = store.conn.execute(
        "SELECT id FROM quality_rule WHERE tenant_id=? AND dataset_id=? AND id=?",
        (tenant, dataset_id, rule_id),
    ).fetchone()
    if row is None:
        raise QualityError(404, "not_found", "not found")
    with store.conn:
        store.conn.execute(
            "DELETE FROM quality_rule WHERE tenant_id=? AND dataset_id=? AND id=?",
            (tenant, dataset_id, rule_id),
        )
    store.audit(tenant, "api", "quality.rule.delete", rule_id, "success", {})


def _observed(rule: dict, frame: pl.DataFrame) -> tuple[str, dict]:
    column_name = rule["column_name"]
    if column_name not in frame.columns:
        return "error", {"violations": 0, "checked": 0, "error": "unknown_column"}
    column = frame[column_name]
    values = _non_null_values(column)
    if rule["kind"] == "not_null":
        checked = frame.height
        violations = _string_nulls(column)
        return ("pass" if violations == 0 else "fail"), {"violations": violations, "checked": checked}
    if rule["kind"] == "unique":
        checked = len(values)
        violations = checked - len(set(values))
        return ("pass" if violations == 0 else "fail"), {"violations": violations, "checked": checked}
    if rule["kind"] == "range":
        minimum = rule["params"].get("min")
        maximum = rule["params"].get("max")
        violations = 0
        for value in values:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                violations += 1
                continue
            if (minimum is not None and numeric < minimum) or (
                maximum is not None and numeric > maximum
            ):
                violations += 1
        return ("pass" if violations == 0 else "fail"), {"violations": violations, "checked": len(values)}
    if rule["kind"] == "regex":
        try:
            pattern = re.compile(rule["params"]["pattern"])
        except (KeyError, re.error):
            return "error", {"violations": 0, "checked": 0, "error": "invalid_pattern"}
        violations = sum(
            1 for value in values if pattern.fullmatch(str(value)) is None
        )
        return ("pass" if violations == 0 else "fail"), {"violations": violations, "checked": len(values)}
    return "error", {"violations": 0, "checked": 0, "error": "unsupported_rule_kind"}


def evaluate_rules(
    store: Store,
    dataset_id: str,
    run_id: str | None = None,
    tenant_id: str | None = None,
    revision: int | None = None,
) -> list[dict]:
    tenant = _tenant_for_dataset(store, dataset_id, tenant_id)
    resolved_revision = _revision_for(store, tenant, dataset_id, revision)
    frame = load_frame(store, tenant, dataset_id, resolved_revision)
    rows = store.conn.execute(
        "SELECT * FROM quality_rule WHERE tenant_id=? AND dataset_id=? ORDER BY created_at ASC",
        (tenant, dataset_id),
    ).fetchall()
    results: list[dict] = []
    for row in rows:
        rule = _rule_dict(row)
        status, observed = _observed(rule, frame)
        result_id = f"qres-{new_id()[:12]}"
        checked_at = now_iso()
        store.execute_with_retry(
            """INSERT INTO quality_result(
                tenant_id, id, rule_id, dataset_id, run_id, status, observed_json, checked_at
            ) VALUES (?,?,?,?,?,?,?,?)""",
            (
                tenant,
                result_id,
                rule["id"],
                dataset_id,
                run_id,
                status,
                json.dumps(observed),
                checked_at,
            ),
        )
        results.append(
            {
                "id": result_id,
                "rule_id": rule["id"],
                "dataset_id": dataset_id,
                "run_id": run_id,
                "status": status,
                "observed": observed,
                "checked_at": checked_at,
                "rule": rule,
            }
        )
    return results


def latest_results(store: Store, tenant: str, dataset_id: str) -> list[dict]:
    rows = store.conn.execute(
        """SELECT r.* FROM quality_rule r
           LEFT JOIN quality_result q
             ON q.tenant_id=r.tenant_id AND q.rule_id=r.id
           WHERE r.tenant_id=? AND r.dataset_id=?
           ORDER BY r.created_at ASC, q.checked_at DESC""",
        (tenant, dataset_id),
    ).fetchall()
    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        result = store.conn.execute(
            """SELECT * FROM quality_result
               WHERE tenant_id=? AND rule_id=? ORDER BY checked_at DESC LIMIT 1""",
            (tenant, row["id"]),
        ).fetchone()
        out.append(
            {
                "rule": _rule_dict(row),
                "latest_result": (
                    {
                        "id": result["id"],
                        "status": result["status"],
                        "observed": json.loads(result["observed_json"] or "{}"),
                        "checked_at": result["checked_at"],
                        "run_id": result["run_id"],
                    }
                    if result is not None
                    else None
                ),
            }
        )
    return out


def profile_rows(store: Store, tenant: str, dataset_id: str) -> tuple[int, list[dict]]:
    dataset = store.conn.execute(
        "SELECT published_revision FROM dataset WHERE tenant_id=? AND id=?", (tenant, dataset_id)
    ).fetchone()
    if dataset is None:
        raise QualityError(404, "not_found", "not found")
    revision = dataset["published_revision"]
    if revision is None:
        return 0, []
    rows = store.conn.execute(
        """SELECT * FROM data_profile
           WHERE tenant_id=? AND dataset_id=? AND revision=? ORDER BY column_name ASC""",
        (tenant, dataset_id, revision),
    ).fetchall()
    return int(revision), [
        {
            "column_name": row["column_name"],
            "dtype": row["dtype"],
            "row_count": row["row_count"],
            "null_count": row["null_count"],
            "null_rate": row["null_rate"],
            "distinct_count": row["distinct_count"],
            "min_value": row["min_value"],
            "max_value": row["max_value"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
