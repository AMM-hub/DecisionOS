"""SQLite-backed control-plane store for the local development worker service.

Mirrors the composite-tenant integrity pattern from the Laravel migrations
(spec §22.2): every tenant-scoped table carries tenant_id in its primary key
and every query is tenant-filtered. Production authority is PostgreSQL via the
Laravel API; this store exists so the pipeline is runnable and testable today.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .migrations import apply_pending


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


import threading
import time


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._all_conns: list[sqlite3.Connection] = []

        # Bootstrap/upgrade database schema on primary connection
        init_conn = self._create_connection()
        apply_pending(init_conn)
        self._local.conn = init_conn

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        if self.path != ":memory:":
            try:
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA synchronous = NORMAL;")
            except sqlite3.OperationalError:
                pass
        with self._lock:
            self._all_conns.append(conn)
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._create_connection()
            self._local.conn = c
        return c

    def execute_with_retry(
        self, query: str, params: tuple | list = (), max_retries: int = 5, backoff_base: float = 0.05
    ) -> sqlite3.Cursor:
        """Execute query with exponential backoff on SQLite lock/busy contention."""
        for attempt in range(max_retries):
            try:
                cur = self.conn.execute(query, params)
                self.conn.commit()
                return cur
            except sqlite3.OperationalError as e:
                err_msg = str(e).lower()
                if ("database is locked" in err_msg or "busy" in err_msg) and attempt < max_retries - 1:
                    time.sleep(backoff_base * (2**attempt))
                    continue
                raise

    # -- helpers ---------------------------------------------------------
    def audit(self, tenant_id: str, actor: str, action: str, target: str, result: str, context: dict | None = None) -> None:
        self.conn.execute(
            "INSERT INTO audit_event(tenant_id, actor, action, target, result, occurred_at, context) VALUES (?,?,?,?,?,?,?)",
            (tenant_id, actor, action, target, result, now_iso(), json.dumps(context or {})),
        )
        self.conn.commit()

    def emit(self, tenant_id: str, event_type: str, aggregate_id: str, aggregate_version: int, payload: dict) -> str:
        event_id = new_id()
        self.conn.execute(
            "INSERT INTO outbox_event(event_id, event_type, schema_version, tenant_id, aggregate_id, aggregate_version, occurred_at, payload) VALUES (?,?,?,?,?,?,?,?)",
            (event_id, event_type, "1.0", tenant_id, aggregate_id, aggregate_version, now_iso(), json.dumps(payload)),
        )
        return event_id

    def save_evidence(self, tenant_id: str, kind: str, payload: dict) -> str:
        eid = new_id()
        self.conn.execute(
            "INSERT INTO evidence(tenant_id, id, kind, payload, created_at) VALUES (?,?,?,?,?)",
            (tenant_id, eid, kind, json.dumps(payload), now_iso()),
        )
        self.conn.commit()
        return f"evidence-{eid[:8]}"

    def close(self) -> None:
        with self._lock:
            for c in self._all_conns:
                try:
                    c.close()
                except sqlite3.Error:
                    pass
            self._all_conns.clear()
        if hasattr(self._local, "conn"):
            self._local.conn = None
