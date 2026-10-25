"""Bearer-token JSON REST connector with bounded pagination.

Error messages contain the HTTP status only: URLs, query strings, and tokens are
never placed in an exception or log line.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from .base import ColumnInfo, Connector, ConnectorError, TableInfo

REQUEST_TIMEOUT = 15
HARD_PAGE_CAP = 100
DEFAULT_PAGE_SIZE = 100


def _dig(data: Any, dotted: str | None) -> Any:
    if not dotted:
        return data
    current = data
    for part in dotted.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _dtype(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, (dict, list)):
        return "json"
    return "string"


class RestConnector(Connector):
    kind = "rest"

    def __init__(
        self,
        config: dict[str, Any],
        secret: str | None = None,
        read_only: bool = True,
        max_rows: int = 50_000,
        max_pages: int = HARD_PAGE_CAP,
    ) -> None:
        self.config = dict(config or {})
        self.base_url = str(self.config.get("base_url") or "").rstrip("/")
        self.secret = secret
        self.read_only = bool(read_only)
        self.max_rows = max(1, int(max_rows))
        self.max_pages = max(1, min(int(max_pages), HARD_PAGE_CAP))
        self.records_path = self.config.get("records_path")
        self.page_param = self.config.get("page_param")
        self.page_size_param = self.config.get("page_size_param")
        self.page_size = max(1, int(self.config.get("page_size", DEFAULT_PAGE_SIZE)))
        if not self.base_url:
            raise ConnectorError("REST source is missing 'base_url'.")

    def _url(self, page: int | None = None, extra: dict[str, Any] | None = None) -> str:
        parsed = urlparse(self.base_url)
        query: dict[str, Any] = {}
        if self.page_param and page is not None:
            query[self.page_param] = page
        if self.page_size_param:
            query[self.page_size_param] = self.page_size
        if extra:
            query.update(extra)
        return urlunparse(parsed._replace(query=urlencode(query)))

    def _get(self, url: str) -> tuple[Any, str]:
        headers = {"Accept": "application/json"}
        if self.secret:
            headers["Authorization"] = f"Bearer {self.secret}"
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310 - configured URL
                body = response.read()
                server = response.headers.get("Server", "rest")
                return json.loads(body.decode("utf-8") or "null"), str(server)
        except HTTPError as exc:
            raise ConnectorError(f"REST source returned HTTP {exc.code}.", status=exc.code) from exc
        except URLError as exc:
            raise ConnectorError("REST source could not be reached.") from exc
        except (UnicodeDecodeError, ValueError) as exc:
            raise ConnectorError("REST source returned invalid JSON.") from exc

    def test_connection(self) -> dict:
        started = time.perf_counter()
        _body, server = self._get(self._url())
        return {
            "status": "connected",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "server_version": server,
        }

    def list_tables(self) -> list[TableInfo]:
        table = str(self.records_path or "records").replace(".", "_")
        return [TableInfo(schema="rest", name=table, kind="view")]

    def describe_table(self, table: str) -> list[ColumnInfo]:
        body, _server = self._get(self._url(page=1))
        records = _dig(body, self.records_path)
        if isinstance(records, dict):
            records = [records]
        if not isinstance(records, list) or not records:
            return []
        first = records[0] if isinstance(records[0], dict) else {}
        return [
            ColumnInfo(name=str(name), dtype=_dtype(value), nullable=True)
            for name, value in first.items()
        ]

    def read_rows(
        self,
        table: str,
        columns: list[str] | None = None,
        limit: int = 50_000,
        offset: int = 0,
        watermark_column: str | None = None,
        watermark_value: Any = None,
    ) -> tuple[list[str], list[list[Any]]]:
        bound = max(1, min(int(limit), self.max_rows))
        extra: dict[str, Any] = {}
        if watermark_column and watermark_value is not None:
            extra[watermark_column] = watermark_value
        header: list[str] | None = list(columns) if columns else None
        rows: list[list[Any]] = []
        skipped = 0
        page = 1
        while page <= self.max_pages and len(rows) < bound:
            body, _server = self._get(self._url(page=page, extra=extra))
            records = _dig(body, self.records_path)
            if isinstance(records, dict):
                records = [records]
            if not isinstance(records, list) or not records:
                break
            for record in records:
                if not isinstance(record, dict):
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                if header is None:
                    header = [str(key) for key in record]
                if columns:
                    row = [record.get(column) for column in columns]
                else:
                    row = [record.get(column) for column in header]
                rows.append(row)
                if len(rows) >= bound:
                    break
            if not self.page_param:
                break
            page += 1
        return header or [], rows
