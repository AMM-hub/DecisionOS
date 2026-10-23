"""Enterprise Security & Cryptographically Signed Authentication Architecture.

Resolves SEC-01 by replacing client-spoofable bare headers with HMAC-SHA256
signed JWT authentication, RBAC role validation, and tenant context isolation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from fastapi import HTTPException

# Master secret key resolution for JWT HMAC-SHA256 signature verification
_DEV_RANDOM_SECRET: str | None = None


def get_jwt_secret() -> str:
    """Resolve active JWT secret according to security policy."""
    strict = os.environ.get("DECISIONOS_AUTH_STRICT", "0") in ("1", "true", "yes")
    secret = os.environ.get("DECISIONOS_JWT_SECRET", "").strip()
    if strict:
        if not secret or len(secret.encode("utf-8")) < 32:
            raise RuntimeError(
                "DECISIONOS_AUTH_STRICT=1 requires DECISIONOS_JWT_SECRET to be configured with at least 32 bytes."
            )
        return secret
    if secret and len(secret.encode("utf-8")) >= 32:
        return secret
    global _DEV_RANDOM_SECRET
    if _DEV_RANDOM_SECRET is None:
        _DEV_RANDOM_SECRET = secrets.token_hex(32)
    return _DEV_RANDOM_SECRET


def __getattr__(name: str) -> Any:
    if name == "JWT_SECRET":
        return get_jwt_secret()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


# Role definitions & RBAC permissions matrix
ROLE_PERMISSIONS: dict[str, set[str]] = {
    # ops_manager may author definitions as well as approve them; separation of duties
    # (a modeler cannot approve their own proposal, §29 QA-018) is enforced on the
    # approve path, not by withholding authorship.
    "ops_manager": {"read", "write", "approve", "transition", "manage_pilot", "trigger_action", "metrics_manage"},
    "semantic_modeler": {"read", "write", "model_create", "metrics_manage"},
    "qa_operator": {"read", "write", "test_ingest", "simulate", "evaluate"},
    "viewer": {"read"},
}


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def create_access_token(
    tenant_id: str,
    user_id: str,
    role: str = "ops_manager",
    expires_in_seconds: int = 86400,
    secret_key: str | None = None,
) -> str:
    """Generate a cryptographically signed HMAC-SHA256 JWT access token."""
    if secret_key is None:
        secret_key = get_jwt_secret()
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "iat": now,
        "exp": now + expires_in_seconds,
    }

    hdr_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    pay_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    hdr_b64 = _b64url_encode(hdr_bytes)
    pay_b64 = _b64url_encode(pay_bytes)

    signing_input = f"{hdr_b64}.{pay_b64}".encode("ascii")
    signature = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)

    return f"{hdr_b64}.{pay_b64}.{sig_b64}"


def verify_access_token(
    token: str,
    secret_key: str | None = None,
) -> dict[str, Any]:
    """Verify cryptographic signature and expiration of an access token."""
    if secret_key is None:
        secret_key = get_jwt_secret()
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise ValueError("Malformed JWT token structure")

    hdr_b64, pay_b64, sig_b64 = parts
    signing_input = f"{hdr_b64}.{pay_b64}".encode("ascii")
    expected_sig = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    actual_sig = _b64url_decode(sig_b64)

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Invalid cryptographic token signature")

    payload = json.loads(_b64url_decode(pay_b64).decode("utf-8"))
    now = int(time.time())

    if "exp" in payload and now > payload["exp"]:
        raise ValueError(f"Token expired at {payload['exp']}, current time is {now}")

    if not payload.get("sub") or not payload.get("tenant_id"):
        raise ValueError("Missing required identity claims in token payload")

    return payload


def has_permission(role: str, action: str) -> bool:
    """Validate whether an RBAC role has the requested action permission."""
    return action in ROLE_PERMISSIONS.get(role, set())


def authenticate_identity(
    authorization: str | None,
    x_tenant: str | None,
    x_user: str | None,
    demo_tenants: set[str],
    demo_users: dict[str, tuple[str, str]],
    strict_auth: bool | None = None,
) -> tuple[str, str, str]:
    """Resolve and authenticate tenant, user, and role with strict cryptographic guarantees.

    Returns:
        (tenant_id, user_id, role)
    """
    if strict_auth is None:
        strict_auth = os.environ.get("DECISIONOS_AUTH_STRICT", "0") in ("1", "true", "yes")

    # 1. Bearer Token Authentication (Cryptographically Signed JWT)
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        try:
            claims = verify_access_token(token)
        except ValueError as err:
            raise HTTPException(status_code=401, detail=f"Invalid authentication token: {err}") from err

        token_tenant = claims["tenant_id"]
        token_user = claims["sub"]
        token_role = claims.get("role", "ops_manager")

        # In strict mode: ignore X-Tenant / X-User entirely; identity comes only from the bearer JWT.
        if not strict_auth:
            # Reject cross-tenant header spoofing if client supplies contradictory X-Tenant in dev mode
            if x_tenant and x_tenant != token_tenant:
                raise HTTPException(status_code=404, detail="not found")

            # Reject cross-user header spoofing if client supplies contradictory X-User
            if x_user and x_user != token_user:
                raise HTTPException(status_code=404, detail="not found")

        return token_tenant, token_user, token_role

    # 2. Strict Authentication Enforcement (SEC-01 Guard)
    if strict_auth:
        raise HTTPException(
            status_code=401,
            detail="Cryptographically signed Bearer token required. Bare header authentication is disabled.",
        )

    # 3. Backward-Compatible Demo Authentication (for legacy test fixtures)
    if x_tenant not in demo_tenants or x_user not in demo_users:
        raise HTTPException(status_code=401, detail="demo authentication missing")

    expected_tenant, role = demo_users[x_user]
    if expected_tenant != x_tenant:
        raise HTTPException(status_code=404, detail="not found")

    return x_tenant, x_user, role
