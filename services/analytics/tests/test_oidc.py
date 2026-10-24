"""OIDC bearer-token verification (no network: JWKS is supplied by a fixture)."""

from __future__ import annotations

import base64
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from decisionos_analytics import security

ISSUER = "http://localhost:8081/realms/decisionos"
AUDIENCE = "decisionos-api"
KID = "decisionos-test-key"

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _jwks_for(private_key) -> dict:
    numbers = private_key.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": KID,
                "use": "sig",
                "alg": "RS256",
                "n": _b64url_uint(numbers.n),
                "e": _b64url_uint(numbers.e),
            }
        ]
    }


JWKS = _jwks_for(_PRIVATE_KEY)


def _token(
    *,
    signing_key=_PRIVATE_KEY,
    kid: str = KID,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    expires_in: int = 300,
    roles: list[str] | None = None,
) -> str:
    now = int(time.time())
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": "alpha.manager",
        "preferred_username": "alpha.manager",
        "iat": now,
        "exp": now + expires_in,
        "realm_access": {"roles": roles or ["ops_manager"]},
        "tenant_id": "tenant_alpha",
    }
    return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": kid, "typ": "JWT"})


@pytest.fixture(autouse=True)
def oidc_configured(monkeypatch):
    security._OIDC_JWKS_CACHE.clear()
    monkeypatch.setenv("DECISIONOS_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("DECISIONOS_OIDC_AUDIENCE", AUDIENCE)
    monkeypatch.setattr(security, "fetch_oidc_jwks", lambda issuer, ttl=None: JWKS)


def test_valid_token_is_accepted_and_role_is_mapped():
    claims = security.verify_oidc_access_token(_token(roles=["offline_access", "semantic_modeler", "viewer"]))
    assert claims["role"] == "semantic_modeler"
    assert claims["tenant_id"] == "tenant_alpha"
    assert claims["sub"] == "alpha.manager"


def test_valid_token_authenticates_api_request(client):
    response = client.get("/v1/pilots", headers={"Authorization": f"Bearer {_token()}"})
    assert response.status_code == 200


def test_wrong_audience_is_rejected():
    with pytest.raises(ValueError, match="(?i)audience"):
        security.verify_oidc_access_token(_token(audience="some-other-api"))


def test_expired_token_is_rejected():
    with pytest.raises(ValueError, match="(?i)expired"):
        security.verify_oidc_access_token(_token(expires_in=-10))


def test_bad_signature_is_rejected():
    with pytest.raises(ValueError, match="(?i)signature"):
        security.verify_oidc_access_token(_token(signing_key=_OTHER_PRIVATE_KEY))


def test_unknown_kid_is_rejected():
    with pytest.raises(ValueError, match="Unknown OIDC signing key"):
        security.verify_oidc_access_token(_token(kid="not-in-jwks"))


def test_issuer_mismatch_is_rejected():
    with pytest.raises(ValueError, match="(?i)issuer"):
        security.verify_oidc_access_token(_token(issuer="http://evil.example/realms/decisionos"))


def test_oidc_disabled_rejects_oidc_token(monkeypatch):
    monkeypatch.delenv("DECISIONOS_OIDC_ISSUER", raising=False)
    with pytest.raises(HTTPException) as exc:
        security.authenticate_identity(
            authorization=f"Bearer {_token()}",
            x_tenant=None,
            x_user=None,
            demo_tenants=set(),
            demo_users={},
        )
    assert exc.value.status_code == 401


def test_jwks_fetch_failure_is_401_not_500(client, monkeypatch):
    def boom(issuer, ttl=None):
        raise ValueError("JWKS endpoint unavailable")

    monkeypatch.setattr(security, "fetch_oidc_jwks", boom)
    response = client.get("/v1/pilots", headers={"Authorization": f"Bearer {_token()}"})
    assert response.status_code == 401
