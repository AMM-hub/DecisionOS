"""Comprehensive Security Tests for Cryptographically Signed JWT & Tenant Boundary (SEC-01)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app
from decisionos_analytics.security import (
    ROLE_PERMISSIONS,
    create_access_token,
    has_permission,
    verify_access_token,
)


@pytest.fixture
def auth_client(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as c:
        yield c


def test_token_creation_and_cryptographic_verification():
    token = create_access_token("tenant_alpha", "alpha.manager", "ops_manager")
    claims = verify_access_token(token)

    assert claims["sub"] == "alpha.manager"
    assert claims["tenant_id"] == "tenant_alpha"
    assert claims["role"] == "ops_manager"
    assert "iat" in claims
    assert "exp" in claims
    assert claims["exp"] > claims["iat"]


def test_forged_token_signature_rejected():
    token = create_access_token("tenant_alpha", "alpha.manager", "ops_manager")
    parts = token.split(".")
    # Tamper with payload (substitute tenant_beta)
    tampered_token = f"{parts[0]}.eyBzdWI6ICJoYWNrZXIiLCB0ZW5hbnRfaWQ6ICJ0ZW5hbnRfYmV0YSIgfQ.{parts[2]}"

    with pytest.raises(ValueError, match="Invalid cryptographic token signature"):
        verify_access_token(tampered_token)


def test_expired_token_rejected():
    # Create token expired 10 seconds ago
    token = create_access_token("tenant_alpha", "alpha.manager", "ops_manager", expires_in_seconds=-10)
    with pytest.raises(ValueError, match="Token expired"):
        verify_access_token(token)


def test_route_access_with_valid_bearer_token(auth_client):
    token = create_access_token("tenant_alpha", "alpha.manager", "ops_manager")
    res = auth_client.get("/v1/pilots", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_route_access_with_invalid_token_rejected_401(auth_client):
    res = auth_client.get("/v1/pilots", headers={"Authorization": "Bearer invalid.token.payload"})
    assert res.status_code == 401


def test_cross_tenant_token_header_mismatch_returns_404(auth_client):
    # Token is for tenant_alpha, but client claims X-Tenant: tenant_beta
    token = create_access_token("tenant_alpha", "alpha.manager", "ops_manager")
    res = auth_client.get(
        "/v1/pilots",
        headers={"Authorization": f"Bearer {token}", "X-Tenant": "tenant_beta"},
    )
    assert res.status_code == 404


def test_strict_mode_rejects_bare_unauthenticated_headers(auth_client, monkeypatch):
    monkeypatch.setenv("DECISIONOS_AUTH_STRICT", "1")
    # In strict mode, bare headers without signed Bearer token are rejected with 401
    res = auth_client.get("/v1/pilots", headers={"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"})
    assert res.status_code == 401
    assert "Cryptographically signed Bearer token required" in res.json()["detail"]


def test_auth_token_issue_and_verify_endpoints(auth_client, monkeypatch):
    monkeypatch.setenv("DECISIONOS_ALLOW_TOKEN_MINT", "1")
    issue_res = auth_client.post(
        "/v1/auth/token",
        json={"tenant_id": "tenant_alpha", "user_id": "alpha.manager", "role": "ops_manager"},
    )
    assert issue_res.status_code == 200
    token_data = issue_res.json()
    assert "access_token" in token_data
    token = token_data["access_token"]

    verify_res = auth_client.get("/v1/auth/verify", headers={"Authorization": f"Bearer {token}"})
    assert verify_res.status_code == 200
    verify_data = verify_res.json()
    assert verify_data["status"] == "authenticated"
    assert verify_data["claims"]["tenant_id"] == "tenant_alpha"


def test_rbac_permissions_matrix():
    assert "ops_manager" in ROLE_PERMISSIONS
    assert has_permission("ops_manager", "approve") is True
    assert has_permission("ops_manager", "transition") is True
    assert has_permission("viewer", "approve") is False
    assert has_permission("semantic_modeler", "metrics_manage") is True
    assert has_permission("qa_operator", "test_ingest") is True
