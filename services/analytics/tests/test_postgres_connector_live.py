"""Live PostgreSQL tests.

Enabled only when a real server is reachable:

    DECISIONOS_TEST_PG_DSN=postgresql://user:pass@127.0.0.1:5432/db pytest tests/test_postgres_connector_live.py

`DECISIONOS_TEST_PG_DSN` is the **connector** DSN and is expected to be a
read-only role, exactly as the product uses it. These tests therefore never
issue DDL against it — they discover an existing table and read from it.

Set `DECISIONOS_TEST_PG_ADMIN_DSN` as well to additionally exercise a
create → insert → read → drop round trip on a throwaway table.
"""

from __future__ import annotations

import os

import pytest

from decisionos_analytics.connectors import ConnectorError
from decisionos_analytics.connectors.postgres import PostgresConnector

DSN = os.environ.get("DECISIONOS_TEST_PG_DSN")
ADMIN_DSN = os.environ.get("DECISIONOS_TEST_PG_ADMIN_DSN")

pytestmark = pytest.mark.skipif(not DSN, reason="DECISIONOS_TEST_PG_DSN is not set")


def _connector(read_only: bool = True) -> PostgresConnector:
    return PostgresConnector({"dsn": DSN}, read_only=read_only)


def _any_readable_table(connector: PostgresConnector) -> str:
    """Return a qualified name of some base table the role can read."""
    for table in connector.list_tables():
        qualified = f"{table.schema}.{table.name}"
        try:
            if connector.describe_table(qualified):
                return qualified
        except Exception:
            continue
    pytest.skip("the connected database exposes no readable base table")


def test_live_connection():
    probe = _connector().test_connection()
    assert probe["status"] == "connected"
    assert probe["server_version"]
    assert probe["latency_ms"] >= 0


def test_live_table_listing_and_read_rows():
    connector = _connector()
    tables = connector.list_tables()
    assert tables, "a connected database should expose at least one table"
    assert all(item.name for item in tables)

    qualified = _any_readable_table(connector)
    columns = connector.describe_table(qualified)
    assert columns
    header, rows = connector.read_rows(qualified, limit=2)
    assert header == [column.name for column in columns]
    assert len(rows) <= 2
    assert all(len(row) == len(header) for row in rows)

    # Bounding is enforced by the connector, not by caller discipline.
    single_header, single_rows = connector.read_rows(qualified, columns=header[:1], limit=1)
    assert single_header == header[:1]
    assert len(single_rows) <= 1


def test_live_read_only_insert_is_refused():
    connector = _connector(read_only=True)
    qualified = _any_readable_table(connector)
    connection = connector._connect()
    try:
        with pytest.raises(Exception) as raised:
            connection.execute(f"INSERT INTO {qualified} DEFAULT VALUES")
        message = str(raised.value).lower()
        # Either the session was forced read-only or the role itself lacks the
        # privilege; both mean "this connector cannot write".
        assert "read-only" in message or "read only" in message or "permission denied" in message
    finally:
        connection.rollback()
        connection.close()


def test_live_bad_credentials_are_a_safe_connector_error():
    connector = PostgresConnector({"host": "127.0.0.1", "port": 1, "dbname": "x"}, connect_timeout=1)
    with pytest.raises(ConnectorError) as raised:
        connector.test_connection()
    assert "password" not in str(raised.value).lower()


@pytest.mark.skipif(not ADMIN_DSN, reason="DECISIONOS_TEST_PG_ADMIN_DSN is not set")
def test_live_round_trip_on_a_throwaway_table():
    import psycopg

    table = "decisionos_connector_roundtrip"
    admin = psycopg.connect(ADMIN_DSN, autocommit=True)
    try:
        admin.execute(f'DROP TABLE IF EXISTS public."{table}"')
        admin.execute(f'CREATE TABLE public."{table}" (id integer NOT NULL, label text)')
        admin.execute(f'INSERT INTO public."{table}" (id, label) VALUES (1, \'a\'), (2, \'b\')')

        connector = _connector()
        assert any(item.name == table for item in connector.list_tables())
        columns = {column.name: column for column in connector.describe_table(f"public.{table}")}
        assert columns["id"].nullable is False

        header, rows = connector.read_rows(f"public.{table}", columns=["id"], limit=1)
        assert header == ["id"]
        assert rows == [[1]]
    finally:
        admin.execute(f'DROP TABLE IF EXISTS public."{table}"')
        admin.close()
