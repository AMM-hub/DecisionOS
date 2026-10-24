"""R9 operational hardening: deep health, request ids, rate limits, metrics, backups."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app

ALPHA = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
REPO_ROOT = Path(__file__).resolve().parents[3]
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "backup_db.py"


def test_health_runs_deep_checks(client):
    response = client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["writable"] is True
    assert "schema_version" in body["checks"]


def test_health_degrades_on_corrupt_database(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        store = app.state.store
        store.close()
        database = tmp_path / "data" / "control.sqlite3"
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{database}{suffix}")
            if sidecar.exists():
                sidecar.unlink()
        database.write_bytes(b"this is not a sqlite database" * 64)

        response = client.get("/v1/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["db"] != "ok"
        assert body["reason"]


def test_request_id_is_echoed_generated_and_in_error_body(client):
    supplied = "req-abc-12345"
    echoed = client.get("/v1/health", headers={"X-Request-Id": supplied})
    assert echoed.headers["X-Request-Id"] == supplied

    generated = client.get("/v1/health")
    request_id = generated.headers["X-Request-Id"]
    assert 8 <= len(request_id) <= 128
    assert set(request_id) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")

    invalid = client.get("/v1/health", headers={"X-Request-Id": "bad id!"})
    assert invalid.headers["X-Request-Id"] != "bad id!"

    error = client.post("/v1/uploads", json={}, headers=ALPHA)
    assert error.status_code == 422
    assert error.json()["request_id"] == error.headers["X-Request-Id"]


def test_rate_limit_per_tenant_and_health_exemption(monkeypatch, tmp_path):
    monkeypatch.setenv("DECISIONOS_RATE_LIMIT", "5")
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        for _ in range(5):
            assert client.get("/v1/datasets", headers=ALPHA).status_code == 200

        limited = client.get("/v1/datasets", headers=ALPHA)
        assert limited.status_code == 429
        assert limited.json()["code"] == "rate_limited"
        assert limited.json()["request_id"] == limited.headers["X-Request-Id"]
        assert "Retry-After" in limited.headers

        for _ in range(10):
            assert client.get("/v1/health").status_code == 200


def test_metrics_keys_and_bounded_latency_ring(monkeypatch, tmp_path):
    monkeypatch.setenv("DECISIONOS_RATE_LIMIT", "0")
    app = create_app(tmp_path / "data")
    metrics = app.state.metrics
    for _ in range(1500):
        metrics.record(200, 1.0, None)

    with TestClient(app) as client:
        response = client.get("/v1/metrics")
        assert response.status_code == 200
        body = response.json()

    assert set(body) >= {"uptime_seconds", "requests_total", "requests_by_status", "errors_by_code", "latency_ms"}
    assert body["latency_ms"]["count"] == 1000
    assert len(metrics.latencies) == 1000


def test_backup_script_creates_verified_snapshot(tmp_path):
    source = tmp_path / "control.sqlite3"
    conn = sqlite3.connect(source)
    try:
        conn.execute("CREATE TABLE widget (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        conn.executemany("INSERT INTO widget(name) VALUES (?)", [("a",), ("b",), ("c",)])
        conn.commit()
    finally:
        conn.close()

    out_dir = tmp_path / "backups"
    result = subprocess.run(
        [sys.executable, str(BACKUP_SCRIPT), "--db", str(source), "--out", str(out_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    snapshots = list(out_dir.glob("control-*.sqlite3"))
    assert len(snapshots) == 1
    snapshot = snapshots[0]

    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    sidecar = Path(f"{snapshot}.sha256").read_text(encoding="utf-8").split()
    assert sidecar[0] == digest

    manifest = json.loads(Path(f"{snapshot}.json").read_text(encoding="utf-8"))
    assert manifest["checks"]["integrity_check"] == "ok"
    assert manifest["checks"]["foreign_key_check"] == "ok"
    assert manifest["checks"]["foreign_key_violations"] == 0
    assert manifest["bytes"] == snapshot.stat().st_size

    check_conn = sqlite3.connect(snapshot)
    try:
        assert check_conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert check_conn.execute("SELECT count(*) FROM widget").fetchone()[0] == 3
    finally:
        check_conn.close()
