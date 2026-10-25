"""Connector contracts for external data sources.

Connectors only ever move data into the bounded ingestion pipeline; they never
create datasets or revisions themselves. Every implementation must bound reads
and must never include credentials in an exception message.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class ConnectorError(Exception):
    """A safe, client-visible connector failure.

    Messages must contain no credentials, DSNs, query strings, or tracebacks.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    dtype: str
    nullable: bool


@dataclass(frozen=True)
class TableInfo:
    schema: str
    name: str
    kind: str


class Connector(ABC):
    """Read-only source adapter used by the ingestion worker."""

    kind: str = "base"

    @abstractmethod
    def test_connection(self) -> dict:
        """Return ``{"status": "connected", "latency_ms": int, "server_version": str}``."""

    @abstractmethod
    def list_tables(self) -> list[TableInfo]:
        ...

    @abstractmethod
    def describe_table(self, table: str) -> list[ColumnInfo]:
        ...

    @abstractmethod
    def read_rows(
        self,
        table: str,
        columns: list[str] | None = None,
        limit: int = 50_000,
        offset: int = 0,
        watermark_column: str | None = None,
        watermark_value: Any = None,
    ) -> tuple[list[str], list[list[Any]]]:
        """Read at most ``limit`` rows. Implementations must apply their own cap."""
