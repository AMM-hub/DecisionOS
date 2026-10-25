"""PostgreSQL source connector built on psycopg 3.

All identifiers are composed with :class:`psycopg.sql.Identifier`; values are
always bound parameters. A read-only connector opens the session with
``default_transaction_read_only = on`` and streaming reads are bounded both by
the caller's limit and the connector's hard ``max_rows`` cap.
"""

from __future__ import annotations

import time
from typing import Any

import psycopg
from psycopg import sql

from .base import ColumnInfo, Connector, ConnectorError, TableInfo

DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_MAX_ROWS = 50_000
_STREAM_CURSOR = "decisionos_read_rows"


def _split_table(table: str) -> tuple[str | None, str]:
    parts = [part for part in table.split(".") if part]
    if len(parts) == 1:
        return None, parts[0]
    if len(parts) == 2:
        return parts[0], parts[1]
    raise ConnectorError("Invalid table identifier; expected table or schema.table.")


def _coerce_watermark(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


class PostgresConnector(Connector):
    kind = "postgres"

    def __init__(
        self,
        config: dict[str, Any],
        secret: str | None = None,
        read_only: bool = True,
        connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
        max_rows: int = DEFAULT_MAX_ROWS,
    ) -> None:
        self.config = dict(config or {})
        self.secret = secret
        self.read_only = bool(read_only)
        self.connect_timeout = int(connect_timeout)
        self.max_rows = max(1, int(max_rows))

    def _connect(self) -> psycopg.Connection:
        dsn = self.config.get("dsn")
        if not dsn and self.secret and "://" in self.secret and not self.config.get("host"):
            dsn = self.secret
        kwargs: dict[str, Any] = {
            "connect_timeout": self.connect_timeout,
            "application_name": "decisionos",
        }
        if not dsn:
            for key in ("host", "port", "dbname", "user"):
                if self.config.get(key) not in (None, ""):
                    kwargs[key] = self.config[key]
            if self.secret:
                kwargs["password"] = self.secret
            elif self.config.get("password"):
                kwargs["password"] = self.config["password"]
        elif self.secret and "://" not in self.secret and not self.config.get("password"):
            kwargs["password"] = self.secret
        try:
            conn = psycopg.connect(dsn, **kwargs) if dsn else psycopg.connect(**kwargs)
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize driver errors to a safe message
            raise ConnectorError("Could not connect to the PostgreSQL source.") from exc
        if self.read_only:
            with conn.cursor() as cur:
                cur.execute("SET default_transaction_read_only = on")
            conn.commit()
        return conn

    def test_connection(self) -> dict:
        started = time.perf_counter()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                row = cur.fetchone()
            version = str(row[0]).split(",")[0] if row else "postgres"
        except Exception as exc:  # noqa: BLE001 - never leak connection details
            raise ConnectorError("PostgreSQL connection test failed.") from exc
        finally:
            conn.close()
        return {
            "status": "connected",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "server_version": version,
        }

    def list_tables(self) -> list[TableInfo]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_schema, table_name, table_type
                    FROM information_schema.tables
                    WHERE table_type IN ('BASE TABLE', 'VIEW')
                      AND table_schema NOT IN ('pg_catalog', 'information_schema')
                    ORDER BY table_schema, table_name
                    """
                )
                rows = cur.fetchall()
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError("Could not list PostgreSQL tables.") from exc
        finally:
            conn.close()
        return [
            TableInfo(
                schema=str(row[0]),
                name=str(row[1]),
                kind="table" if row[2] == "BASE TABLE" else "view",
            )
            for row in rows
        ]

    def describe_table(self, table: str) -> list[ColumnInfo]:
        schema, name = _split_table(table)
        # Two statement shapes instead of `(%s IS NULL OR table_schema = %s)`:
        # psycopg 3 cannot infer the type of a bare NULL parameter, and Postgres
        # rejects the query with "could not determine data type of parameter $2".
        if schema:
            query = (
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = %s AND table_schema = %s "
                "ORDER BY ordinal_position"
            )
            params: tuple = (name, schema)
        else:
            query = (
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = %s "
                "ORDER BY ordinal_position"
            )
            params = (name,)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError("Could not describe the PostgreSQL table.") from exc
        finally:
            conn.close()
        return [
            ColumnInfo(name=str(row[0]), dtype=str(row[1]), nullable=row[2] == "YES")
            for row in rows
        ]

    def _select_statement(
        self,
        table: str,
        columns: list[str] | None,
        watermark_column: str | None,
    ) -> sql.Composed:
        schema, name = _split_table(table)
        target = sql.Identifier(schema, name) if schema else sql.Identifier(name)
        projection = (
            sql.SQL(", ").join(sql.Identifier(column) for column in columns)
            if columns
            else sql.SQL("*")
        )
        statement = sql.SQL("SELECT {} FROM {}").format(projection, target)
        if watermark_column:
            statement += sql.SQL(" WHERE {} > %s").format(sql.Identifier(watermark_column))
        return statement

    def read_rows(
        self,
        table: str,
        columns: list[str] | None = None,
        limit: int = DEFAULT_MAX_ROWS,
        offset: int = 0,
        watermark_column: str | None = None,
        watermark_value: Any = None,
    ) -> tuple[list[str], list[list[Any]]]:
        bound = max(1, min(int(limit), self.max_rows))
        statement = self._select_statement(table, columns, watermark_column)
        params: list[Any] = []
        if watermark_column and watermark_value is not None:
            params.append(_coerce_watermark(watermark_value))
        if offset:
            statement += sql.SQL(" OFFSET %s")
            params.append(int(offset))
        statement += sql.SQL(" LIMIT %s")
        params.append(bound)

        conn = self._connect()
        try:
            with conn.cursor(name=_STREAM_CURSOR) as cur:
                cur.execute(statement, params)
                header: list[str] | None = list(columns) if columns else None
                rows: list[list[Any]] = []
                for record in cur:
                    if header is None:
                        header = [desc.name for desc in (cur.description or [])]
                    if len(rows) >= bound:
                        break
                    rows.append(list(record))
                if header is None:
                    header = []
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError("Could not read rows from the PostgreSQL source.") from exc
        finally:
            conn.close()
        return header, rows
