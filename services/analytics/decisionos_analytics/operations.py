"""Operational hardening primitives for the analytics control plane.

This module is deliberately dependency-free (stdlib only) so the control plane
keeps working in the slim production image.

Rate limiting is an **in-process token bucket**. It is scoped to a single
process and does **not** coordinate across replicas: two uvicorn workers, or two
containers behind a load balancer, each get their own budget. It is a safety
valve for a single node, not a distributed quota. Deployments that need a
cluster-wide limit must enforce it at the edge or in a shared store.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
from collections import deque
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
_RING_BUFFER_SIZE = 1000
_DEFAULT_RATE_LIMIT = 120

request_id_var: ContextVar[str | None] = ContextVar("decisionos_request_id", default=None)
_actor_var: ContextVar[dict[str, str | None] | None] = ContextVar("decisionos_actor", default=None)


def valid_or_new_request_id(raw: str | None) -> str:
    """Return the inbound id when it matches the contract, otherwise a fresh uuid."""
    if raw and _REQUEST_ID_RE.fullmatch(raw):
        return raw
    import uuid

    return uuid.uuid4().hex


def bind_request(request_id: str) -> tuple[Any, Any]:
    """Bind the per-request context; returns tokens for the eventual reset."""
    rid_token = request_id_var.set(request_id)
    actor_token = _actor_var.set({"tenant": None, "user": None})
    return rid_token, actor_token


def reset_request(rid_token: Any, actor_token: Any) -> None:
    _actor_var.reset(actor_token)
    request_id_var.reset(rid_token)


def current_request_id() -> str | None:
    return request_id_var.get()


def bind_actor(tenant: str | None, user: str | None) -> None:
    actor = _actor_var.get()
    if actor is None:
        actor = {"tenant": None, "user": None}
        _actor_var.set(actor)
    actor["tenant"] = tenant
    actor["user"] = user


def current_actor() -> dict[str, str | None]:
    return dict(_actor_var.get() or {"tenant": None, "user": None})


# ---- structured logging ---------------------------------------------------


class JSONFormatter(logging.Formatter):
    """Minimal JSON formatter: no third-party dependency, one line per record."""

    _EXTRA_FIELDS = ("method", "path", "status", "duration_ms", "tenant", "user")

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = getattr(record, "request_id", None) or current_request_id()
        if rid:
            payload["request_id"] = rid
        for field in self._EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Configure the root logger once; safe to call from every create_app()."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        level_name = "WARNING"
    else:
        level_name = os.environ.get("DECISIONOS_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    if not isinstance(level, int):
        level = logging.INFO

    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        if getattr(handler, "_decisionos_json", False):
            handler.setLevel(level)
            return
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(JSONFormatter())
    handler._decisionos_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)


# ---- health ---------------------------------------------------------------


def _short_reason(exc: BaseException) -> str:
    message = str(exc).strip().replace("\n", " ")
    return message[:200] or exc.__class__.__name__


def _schema_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if row is None:
        return None
    columns = [info[1] for info in conn.execute("PRAGMA table_info(schema_version)").fetchall()]
    if "version" not in columns:
        return None
    latest = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
    if latest is None or latest[0] is None:
        return None
    try:
        return int(latest[0])
    except (TypeError, ValueError):
        return None


def check_store_health(store: Any) -> tuple[bool, dict[str, Any], str | None]:
    """Run quick_check, schema discovery, and a rollback-only write probe."""
    checks: dict[str, Any] = {"db": "error", "schema_version": None, "writable": False}
    reason: str | None = None
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(store.path, timeout=0.2)
        try:
            rows = conn.execute("PRAGMA quick_check").fetchall()
            healthy = len(rows) == 1 and rows[0][0] == "ok"
            if not healthy:
                checks["db"] = "corrupt"
                if not reason:
                    reason = "database quick_check did not return ok"
            else:
                checks["db"] = "ok"
                checks["schema_version"] = _schema_version(conn)
        except sqlite3.Error as exc:
            checks["db"] = "corrupt"
            reason = _short_reason(exc)

        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
            checks["writable"] = True
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            checks["writable"] = False
            if not reason:
                reason = _short_reason(exc)
    except sqlite3.Error as exc:
        reason = _short_reason(exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    healthy = checks["db"] == "ok" and checks["writable"] is True
    if healthy:
        return True, checks, None
    return False, checks, reason or "database health check failed"


# ---- rate limiting --------------------------------------------------------


class TokenBucketLimiter:
    """Per-process, keyed token bucket (requests per minute, 0 disables)."""

    def __init__(self, requests_per_minute: int = _DEFAULT_RATE_LIMIT) -> None:
        self.limit = max(0, int(requests_per_minute))
        self.capacity = float(self.limit)
        self.rate_per_second = self.limit / 60.0
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        """Consume one token; return (allowed, retry_after_seconds)."""
        if self.limit == 0:
            return True, 0
        now = time.monotonic()
        with self._lock:
            if len(self._buckets) > 10_000:
                self._prune(now)
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + max(0.0, now - last) * self.rate_per_second)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                return True, 0
            self._buckets[key] = (tokens, now)
            retry_after = math.ceil((1.0 - tokens) / self.rate_per_second) if self.rate_per_second else 60
            return False, max(1, retry_after)

    def _prune(self, now: float) -> None:
        stale = [
            key
            for key, (tokens, last) in self._buckets.items()
            if tokens >= self.capacity and (now - last) > 120.0
        ]
        for key in stale:
            self._buckets.pop(key, None)


def rate_limit_from_env() -> int:
    raw = os.environ.get("DECISIONOS_RATE_LIMIT", str(_DEFAULT_RATE_LIMIT)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_RATE_LIMIT


# ---- metrics --------------------------------------------------------------


class Metrics:
    """Bounded, thread-safe request metrics with a 1000-sample latency ring."""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.requests_total = 0
        self.requests_by_status: dict[str, int] = {}
        self.errors_by_code: dict[str, int] = {}
        self.latencies: deque[float] = deque(maxlen=_RING_BUFFER_SIZE)
        self._lock = threading.Lock()

    def record(self, status: int, duration_ms: float, error_code: str | None = None) -> None:
        with self._lock:
            self.requests_total += 1
            status_key = str(status)
            self.requests_by_status[status_key] = self.requests_by_status.get(status_key, 0) + 1
            if error_code:
                self.errors_by_code[error_code] = self.errors_by_code.get(error_code, 0) + 1
            self.latencies.append(float(duration_ms))

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        index = max(0, math.ceil((percentile / 100.0) * len(values)) - 1)
        return values[min(index, len(values) - 1)]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            values = sorted(self.latencies)
            return {
                "uptime_seconds": round(time.monotonic() - self.started, 3),
                "requests_total": self.requests_total,
                "requests_by_status": dict(self.requests_by_status),
                "errors_by_code": dict(self.errors_by_code),
                "latency_ms": {
                    "p50": round(self._percentile(values, 50), 3),
                    "p95": round(self._percentile(values, 95), 3),
                    "p99": round(self._percentile(values, 99), 3),
                    "count": len(values),
                },
            }
