"""Connector registry and credential redaction."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from ..ai.crypto import decrypt_secret
from .base import Connector, ConnectorError
from .postgres import PostgresConnector
from .rest import RestConnector

CONNECTORS: dict[str, type[Connector]] = {
    "postgres": PostgresConnector,
    "rest": RestConnector,
}

_SENSITIVE_KEY = re.compile(r"password|secret|token|dsn|key", re.IGNORECASE)


def _mask_dsn(value: str) -> str:
    parsed = urlparse(value)
    if not parsed.scheme:
        return "dsn://redacted"
    host = parsed.hostname or "redacted"
    database = (parsed.path or "").lstrip("/") or "redacted"
    return f"{parsed.scheme}://{host}/{database}"


def redact_config(config: Any) -> dict[str, Any]:
    """Drop credential-bearing keys; never return a secret substring.

    A ``dsn`` is replaced with ``scheme://host/db`` because operators still need
    to see which database a source points at.
    """
    if not isinstance(config, dict):
        return {}
    redacted: dict[str, Any] = {}
    for key, value in config.items():
        if _SENSITIVE_KEY.search(str(key)):
            if str(key).lower() == "dsn" and isinstance(value, str):
                redacted[key] = _mask_dsn(value)
            continue
        if isinstance(value, dict):
            redacted[key] = redact_config(value)
        else:
            redacted[key] = value
    return redacted


def get_connector(row: Any) -> Connector:
    """Build a connector from a ``data_source`` row (sqlite Row or dict)."""
    try:
        kind = row["kind"]
        config = json.loads(row["config_json"] or "{}")
    except (KeyError, TypeError, ValueError) as exc:
        raise ConnectorError("Stored data source configuration is invalid.") from exc
    if not isinstance(config, dict):
        raise ConnectorError("Stored data source configuration is invalid.")
    connector_cls = CONNECTORS.get(kind)
    if connector_cls is None:
        raise ConnectorError(f"Unsupported connector kind '{kind}'.")
    ciphertext = row["secret_ciphertext"] if "secret_ciphertext" in row.keys() else None
    try:
        secret = decrypt_secret(ciphertext) if ciphertext else None
    except (ValueError, TypeError) as exc:
        raise ConnectorError(
            "Stored data source credential could not be decrypted. The API and this "
            "process must use the same DECISIONOS_SECRET_KEY and data directory."
        ) from exc
    read_only = bool(row["read_only"]) if "read_only" in row.keys() else True
    max_rows = None
    try:
        max_rows = row["max_rows"] if "max_rows" in row.keys() else None
    except (IndexError, KeyError):
        max_rows = None
    kwargs: dict[str, Any] = {
        "config": config,
        "secret": secret,
        "read_only": read_only,
    }
    if kind == "postgres" and max_rows:
        kwargs["max_rows"] = int(max_rows)
    elif kind == "rest" and max_rows:
        kwargs["max_rows"] = int(max_rows)
    return connector_cls(**kwargs)
