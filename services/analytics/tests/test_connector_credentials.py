"""Connector credential handling and data-directory resolution.

Both of these were real field bugs found by driving the stack against a live
PostgreSQL server — the mocked unit tests around them were green beforehand.
"""

from __future__ import annotations

import json
from pathlib import Path

from decisionos_analytics.config import PACKAGE_ROOT, resolve_data_dir


def _create(client, headers, config, secret=None, name="pg-one"):
    body = {"name": name, "kind": "postgres", "read_only": True, "config": config}
    if secret is not None:
        body["secret"] = secret
    return client.post("/v1/connectors", headers=headers, json=body)


def test_passwordless_dsn_keeps_connection_details(client, alpha_headers):
    """A DSN without a password used to be dropped entirely.

    The old `_extract_secret` popped `dsn` whenever it contained '@' and kept
    only the password, so the stored source had no host and every later
    connection failed with "Could not connect to the PostgreSQL source."
    """
    response = _create(
        client,
        alpha_headers,
        {"dsn": "postgresql://decisionos_ro@db.internal:5433/analytics_fixture"},
        secret="s3cret",
    )
    assert response.status_code == 201, response.text
    payload = response.json()

    config = payload["config"]
    assert "dsn" not in config
    assert config["host"] == "db.internal"
    assert config["port"] == 5433
    assert config["dbname"] == "analytics_fixture"
    assert config["user"] == "decisionos_ro"
    assert "s3cret" not in json.dumps(payload)


def test_dsn_with_embedded_password_is_split_into_a_secret(client, alpha_headers):
    response = _create(
        client,
        alpha_headers,
        {"dsn": "postgresql://reader:hunter2@db.internal:5432/analytics_fixture"},
        name="pg-two",
    )
    assert response.status_code == 201, response.text
    payload = response.json()

    config = payload["config"]
    assert "hunter2" not in json.dumps(payload)
    assert config.get("password") is None
    assert config["host"] == "db.internal"
    assert config["user"] == "reader"


def test_stored_connector_rebuilds_the_same_target(client, alpha_headers):
    """The connector built from the stored row must point at the same server."""
    from decisionos_analytics.connectors import get_connector

    response = _create(
        client,
        alpha_headers,
        {"dsn": "postgresql://decisionos_ro@127.0.0.1:5432/decisionos_fixture"},
        secret="ro_pass_2026",
        name="pg-three",
    )
    connector_id = response.json()["id"]
    store = client.app.state.store
    row = store.conn.execute(
        "SELECT * FROM data_source WHERE tenant_id=? AND id=?", ("tenant_alpha", connector_id)
    ).fetchone()

    connector = get_connector(row)
    assert connector.config["host"] == "127.0.0.1"
    assert connector.config["dbname"] == "decisionos_fixture"
    assert connector.secret == "ro_pass_2026"


def test_listing_never_returns_the_secret(client, alpha_headers):
    _create(
        client,
        alpha_headers,
        {"dsn": "postgresql://decisionos_ro@127.0.0.1:5432/decisionos_fixture"},
        secret="ro_pass_2026",
        name="pg-four",
    )
    listed = client.get("/v1/connectors", headers=alpha_headers)
    assert listed.status_code == 200
    assert "ro_pass_2026" not in listed.text
    assert "password" not in listed.text.lower()


def test_relative_data_dir_is_anchored_to_the_package_root(monkeypatch):
    """Two processes with different CWDs must resolve the same database.

    The API (started in services/analytics) and the worker (started elsewhere)
    used to open different SQLite files from the same relative env var: the run
    stayed `queued` forever while the worker logged "idle".
    """
    monkeypatch.setenv("DECISIONOS_DATA_DIR", "./var/shared")
    resolved = resolve_data_dir()
    assert resolved.is_absolute()
    assert resolved == (PACKAGE_ROOT / "var" / "shared").resolve()

    monkeypatch.setenv("DECISIONOS_DATA_DIR", str(Path("C:/tmp/absolute")))
    assert resolve_data_dir() == Path("C:/tmp/absolute").resolve()


def test_explicit_data_dir_argument_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("DECISIONOS_DATA_DIR", "./var/ignored")
    assert resolve_data_dir(tmp_path) == tmp_path.resolve()
