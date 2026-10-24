"""Encryption at rest for AI provider credentials.

Provider keys are encrypted with AES-GCM. The master key comes from
``DECISIONOS_SECRET_KEY`` (>= 32 bytes). During local development a stable key
is kept in ``$DECISIONOS_DATA_DIR/.ai_key`` (mode 0600) so restarts keep
working without placing a secret in the environment. Strict deployments must
provide ``DECISIONOS_SECRET_KEY``; boot fails fast when they do not.

The plaintext key is never logged, returned by an endpoint, or included in an
error body. The wire format is ``v1:<base64 nonce>:<base64 ciphertext>``.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_BYTES = 32
_NONCE_BYTES = 12
_AAD = b"decisionos-ai-provider-key-v1"
_PREFIX = "v1"
_KEY_FILE_NAME = ".ai_key"

_configured_data_dir: Path | None = None


def configure(data_dir: Path | str | None = None) -> None:
    """Record the application's data directory for the development key file."""
    global _configured_data_dir
    if data_dir is not None:
        _configured_data_dir = Path(data_dir)


def _strict_mode() -> bool:
    return os.environ.get("DECISIONOS_AUTH_STRICT", "0") in ("1", "true", "yes")


def _data_dir() -> Path:
    if _configured_data_dir is not None:
        return _configured_data_dir
    raw = os.environ.get("DECISIONOS_DATA_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path("./var/worker")


def _derive_key(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _read_or_create_dev_key() -> bytes:
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    key_path = data_dir / _KEY_FILE_NAME

    if key_path.exists():
        material = key_path.read_bytes()
        if len(material) >= _KEY_BYTES:
            return material[:_KEY_BYTES]
        raise RuntimeError(
            f"AI key file {key_path} is corrupt (expected at least {_KEY_BYTES} bytes); "
            "delete it to regenerate a development key."
        )

    material = secrets.token_bytes(_KEY_BYTES)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(key_path, flags, 0o600)
    except FileExistsError:
        existing = key_path.read_bytes()
        if len(existing) >= _KEY_BYTES:
            return existing[:_KEY_BYTES]
        raise RuntimeError(f"AI key file {key_path} was created but is corrupt.") from None
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(material)
    except OSError:
        try:
            key_path.unlink(missing_ok=True)
        finally:
            raise
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    return material


def get_master_key() -> bytes:
    """Resolve the 32-byte AES key without ever exposing it to callers' output."""
    secret = os.environ.get("DECISIONOS_SECRET_KEY", "").strip()
    if secret:
        if len(secret.encode("utf-8")) < _KEY_BYTES and _strict_mode():
            raise RuntimeError(
                "DECISIONOS_AUTH_STRICT=1 requires DECISIONOS_SECRET_KEY to be configured with at least 32 bytes."
            )
        return _derive_key(secret)
    if _strict_mode():
        raise RuntimeError(
            "DECISIONOS_AUTH_STRICT=1 requires DECISIONOS_SECRET_KEY to be configured with at least 32 bytes "
            "so AI provider keys can be encrypted at rest."
        )
    return _read_or_create_dev_key()


def ensure_configured(data_dir: Path | str | None = None) -> None:
    """Fail fast at boot when strict mode has no usable encryption key."""
    configure(data_dir)
    get_master_key()


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def encrypt_secret(plaintext: str) -> str:
    if not isinstance(plaintext, str) or not plaintext:
        raise ValueError("secret must be a non-empty string")
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ciphertext = AESGCM(get_master_key()).encrypt(nonce, plaintext.encode("utf-8"), _AAD)
    return f"{_PREFIX}:{_b64encode(nonce)}:{_b64encode(ciphertext)}"


def decrypt_secret(token: str) -> str:
    if not isinstance(token, str):
        raise ValueError("ciphertext must be a string")
    parts = token.split(":", 2)
    if len(parts) != 3 or parts[0] != _PREFIX:
        raise ValueError("unsupported ciphertext format")
    try:
        nonce = _b64decode(parts[1])
        ciphertext = _b64decode(parts[2])
    except (ValueError, TypeError) as exc:
        raise ValueError("malformed ciphertext") from exc
    if len(nonce) != _NONCE_BYTES:
        raise ValueError("malformed ciphertext nonce")
    try:
        plaintext = AESGCM(get_master_key()).decrypt(nonce, ciphertext, _AAD)
    except Exception as exc:  # cryptography raises InvalidTag, not a public ValueError
        raise ValueError("ciphertext authentication failed") from exc
    return plaintext.decode("utf-8")


def key_fingerprint() -> str:
    """A stable 8-character public fingerprint of the active master key."""
    return hashlib.sha256(get_master_key()).hexdigest()[:8]
