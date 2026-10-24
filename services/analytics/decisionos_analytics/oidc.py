"""OpenID Connect access-token verification (RS256 / JWKS).

The local control plane normally verifies HMAC tokens minted by the demo
``/v1/auth/token`` endpoint. When a real identity provider is configured
(``DECISIONOS_OIDC_ISSUER``) the same bearer header may instead carry an OIDC
access token. This module performs the cryptographic verification and maps the
provider's realm roles onto the application's RBAC vocabulary.
"""

from __future__ import annotations

from typing import Any

import jwt
from jwt import PyJWK

# Highest privilege first: a token carrying several realm roles maps to the
# strongest one the application understands.
APP_ROLE_PRIORITY: tuple[str, ...] = (
    "ops_manager",
    "semantic_modeler",
    "qa_operator",
    "viewer",
)


class OIDCError(ValueError):
    """Raised when an OIDC token cannot be trusted."""


def _key_for_kid(jwks: dict[str, Any], kid: str | None) -> Any:
    if not kid:
        raise OIDCError("OIDC token header is missing a key id (kid)")
    for jwk in jwks.get("keys", []):
        if jwk.get("kid") == kid:
            try:
                return PyJWK(jwk).key
            except (ValueError, TypeError, KeyError, jwt.PyJWTError) as err:
                raise OIDCError(f"OIDC signing key '{kid}' is malformed") from err
    raise OIDCError(f"Unknown OIDC signing key id '{kid}'")


def _string_claim(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _tenant_from_claims(claims: dict[str, Any]) -> str | None:
    tenant = _string_claim(claims.get("tenant_id"))
    if tenant:
        return tenant
    for container in ("user_attributes", "attributes"):
        attributes = claims.get(container)
        if isinstance(attributes, dict):
            tenant = _string_claim(attributes.get("tenant_id"))
            if tenant:
                return tenant
    return None


def _role_from_claims(claims: dict[str, Any]) -> str | None:
    roles: set[str] = set()
    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict):
        roles.update(str(r) for r in realm_access.get("roles", []) if r)
    raw_roles = claims.get("roles")
    if isinstance(raw_roles, list):
        roles.update(str(r) for r in raw_roles if r)
    return next((role for role in APP_ROLE_PRIORITY if role in roles), None)


def verify_oidc_token(
    token: str,
    issuer: str,
    audience: str,
    jwks: dict[str, Any],
) -> dict[str, Any]:
    """Verify an RS256 OIDC access token against a JWKS document.

    Checks the signature using the header ``kid``, then ``exp``/``iss``/``aud``.
    Returns the claims enriched with the application ``role`` and ``tenant_id``.
    """
    if not issuer or not audience:
        raise OIDCError("OIDC issuer and audience are required")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as err:
        raise OIDCError("Malformed OIDC token header") from err

    if header.get("alg") != "RS256":
        raise OIDCError("OIDC tokens must be signed with RS256")

    key = _key_for_kid(jwks, header.get("kid"))

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "iss", "aud"]},
        )
    except jwt.PyJWTError as err:
        raise OIDCError(f"Invalid OIDC token: {err}") from err

    role = _role_from_claims(claims)
    if role is None:
        raise OIDCError("OIDC token carries no recognised application role")
    tenant = _tenant_from_claims(claims)
    if tenant is None:
        raise OIDCError("OIDC token carries no tenant_id attribute")

    claims["role"] = role
    claims["tenant_id"] = tenant
    return claims
