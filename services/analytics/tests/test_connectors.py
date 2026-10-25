from __future__ import annotations

import json

import pytest

from decisionos_analytics.connectors import CONNECTORS, ConnectorError, get_connector, redact_config
from decisionos_analytics.connectors.postgres import PostgresConnector
from decisionos_analytics.connectors.rest import RestConnector


class FakeDescription:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.description = [FakeDescription("id")]

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, query, params=None) -> None:
        self.connection.executed.append((query, params))
        self.connection.last_query = query
        if "default_transaction_read_only" in str(query):
            self.connection.read_only = True

    def fetchone(self):
        return self.connection.fetchone_result

    def fetchall(self):
        return self.connection.fetchall_result

    def __iter__(self):
        return iter(self.connection.rows)


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[object, object]] = []
        self.fetchone_result = ("PostgreSQL 16.2 on x86_64",)
        self.fetchall_result: list[tuple] = []
        self.rows: list[list] = []
        self.closed = False
        self.read_only = False

    def execute(self, query, params=None):
        text = str(query)
        self.executed.append((query, params))
        if "default_transaction_read_only" in text:
            self.read_only = True
        if "INSERT" in text.upper() and self.read_only:
            raise RuntimeError("read-only transaction")
        return self

    def commit(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def cursor(self, name=None, **kwargs) -> FakeCursor:
        return FakeCursor(self)


def test_redaction_never_leaks_secret_substrings():
    config = {
        "host": "db.internal",
        "user": "analyst",
        "password": "sup3r-secret-password",
        "dsn": "postgresql://analyst:sup3r-secret-password@db.internal:5432/app",
        "nested": {"token": "tok-live-123", "api_key": "key-live-456"},
    }
    redacted = redact_config(config)
    dumped = json.dumps(redacted)
    assert "sup3r-secret-password" not in dumped
    assert "tok-live-123" not in dumped
    assert "key-live-456" not in dumped
    assert redacted["dsn"] == "postgresql://db.internal/app"
    assert redacted["host"] == "db.internal"


def test_registry_lookup():
    assert CONNECTORS["postgres"] is PostgresConnector
    assert CONNECTORS["rest"] is RestConnector
    assert isinstance(
        get_connector(
            {
                "kind": "postgres",
                "config_json": json.dumps({"host": "db", "user": "u"}),
                "secret_ciphertext": None,
                "read_only": 1,
            }
        ),
        PostgresConnector,
    )
    assert isinstance(
        get_connector(
            {
                "kind": "rest",
                "config_json": json.dumps({"base_url": "https://example.test"}),
                "secret_ciphertext": None,
                "read_only": 1,
            }
        ),
        RestConnector,
    )


def test_registry_refuses_unknown_kind():
    with pytest.raises(ConnectorError):
        get_connector(
            {
                "kind": "mysql",
                "config_json": "{}",
                "secret_ciphertext": None,
                "read_only": 1,
            }
        )


def test_read_only_sets_default_transaction_read_only(monkeypatch):
    import decisionos_analytics.connectors.postgres as postgres_module

    fake = FakeConnection()
    monkeypatch.setattr(postgres_module.psycopg, "connect", lambda *a, **k: fake)
    connector = PostgresConnector({"host": "db", "user": "u"}, secret="pw", read_only=True)
    probe = connector.test_connection()
    assert probe["status"] == "connected"
    assert any("default_transaction_read_only" in str(query) for query, _ in fake.executed)
    assert fake.read_only is True
    with pytest.raises(RuntimeError):
        fake.execute("INSERT INTO tickets VALUES (1)")


def test_identifier_quoting_and_max_rows_bound(monkeypatch):
    import decisionos_analytics.connectors.postgres as postgres_module

    fake = FakeConnection()
    fake.rows = [[index] for index in range(100)]
    monkeypatch.setattr(postgres_module.psycopg, "connect", lambda *a, **k: fake)
    connector = PostgresConnector({"host": "db"}, secret="pw", max_rows=5)

    statement = connector._select_statement("public.tickets", ["id"], "updated_at")
    rendered = statement.as_string(None)
    assert '"public"."tickets"' in rendered
    assert '"id"' in rendered
    assert '"updated_at"' in rendered

    header, rows = connector.read_rows("public.tickets", ["id"], limit=100)
    assert header == ["id"]
    assert len(rows) == 5
    query, params = fake.executed[-1]
    assert "LIMIT %s" in query.as_string(None)
    assert params[-1] == 5


def test_rest_connector_never_puts_query_string_in_errors(monkeypatch):
    import decisionos_analytics.connectors.rest as rest_module

    def explode(*args, **kwargs):
        from urllib.error import HTTPError

        raise HTTPError("https://api.test/data?token=secret", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(rest_module, "urlopen", explode)
    connector = RestConnector({"base_url": "https://api.test/data"}, secret="tok-secret")
    with pytest.raises(ConnectorError) as raised:
        connector.test_connection()
    assert "401" in str(raised.value)
    assert "secret" not in str(raised.value)
    assert "api.test" not in str(raised.value)


def test_connector_api_never_echoes_secret(client, alpha_headers):
    response = client.post(
        "/v1/connectors",
        json={
            "name": "Warehouse",
            "kind": "rest",
            "config": {"base_url": "https://api.test/v1", "token": "sk-live-secret-value"},
            "secret": "sk-live-secret-value",
        },
        headers=alpha_headers,
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert "sk-live-secret-value" not in json.dumps(created)
    assert created["has_secret"] is True
    assert "token" not in created["config"]

    connector_id = created["id"]
    listed = client.get("/v1/connectors", headers=alpha_headers)
    assert listed.status_code == 200
    assert "sk-live-secret-value" not in listed.text
    single = client.get(f"/v1/connectors/{connector_id}", headers=alpha_headers)
    assert single.status_code == 200
    assert "sk-live-secret-value" not in single.text
    beta = {"X-Tenant": "tenant_beta", "X-User": "beta.manager"}
    assert client.get("/v1/connectors", headers=beta).json() == []
    assert client.get(f"/v1/connectors/{connector_id}", headers=beta).status_code == 404
