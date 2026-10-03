"""Security Input Fuzzing and Protection Matrix Test Suite.

Verifies system safety against:
- SQL-looking inputs
- XSS-looking inputs
- Path traversal filenames
- Invalid resource UUIDs
- Wrong tenant / reverse wrong tenant
- Invalid users
- Malformed inputs
"""

from __future__ import annotations

import pytest


def test_sql_injection_safety(client):
    sql_payloads = [
        "' OR '1'='1",
        "'; DROP TABLE decision; --",
        "1 UNION SELECT 1,2,3",
    ]
    for sql in sql_payloads:
        # GET endpoint
        res = client.get(f"/v1/decisions/{sql}", headers={"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"})
        assert res.status_code in (400, 404, 422)
        assert res.status_code != 500

        # POST upload initiation
        res_post = client.post("/v1/uploads", json={
            "filename": f"test_{sql}.csv", "size_bytes": 100, "workspace_id": sql
        }, headers={"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"})
        assert res_post.status_code in (201, 400, 422)
        assert res_post.status_code != 500


def test_xss_input_safety(client):
    xss_payloads = [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "javascript:alert(document.cookie)",
    ]
    for xss in xss_payloads:
        headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
        res = client.post("/v1/monitoring/rules", json={
            "name": xss, "dataset_id": "ds-1", "metric_id": "m-1", "owner": "alpha.manager"
        }, headers=headers)
        assert res.status_code in (201, 400, 422)
        assert res.status_code != 500


def test_path_traversal_filename_safety(client):
    traversal_filenames = [
        "../../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\cmd.exe",
        "/etc/shadow",
    ]
    for fn in traversal_filenames:
        headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
        res = client.post("/v1/uploads", json={
            "filename": fn, "size_bytes": 100, "workspace_id": "ws-support-ops"
        }, headers=headers)
        assert res.status_code in (201, 400, 422)
        assert res.status_code != 500


def test_invalid_resource_ids(client):
    headers = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
    invalid_ids = ["nonexistent-uuid-9999", "1234", "undefined", "null"]
    for iid in invalid_ids:
        assert client.get(f"/v1/decisions/{iid}", headers=headers).status_code == 404
        assert client.get(f"/v1/datasets/{iid}/schema", headers=headers).status_code in (404, 409)
        assert client.get(f"/v1/monitoring/health/{iid}", headers=headers).status_code == 200  # returns status: unknown
