from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from decisionos_analytics.api import create_app  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "support-tickets" / "data"


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def alpha_headers():
    return {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}


@pytest.fixture()
def modeler_headers():
    return {"X-Tenant": "tenant_alpha", "X-User": "alpha.modeler"}


@pytest.fixture()
def beta_headers():
    return {"X-Tenant": "tenant_beta", "X-User": "beta.manager"}


def upload_and_finalize(client, headers, path: Path, filename: str | None = None):
    name = filename or path.name
    r = client.post("/v1/uploads", json={"filename": name, "size_bytes": path.stat().st_size, "workspace_id": "ws-support-ops"}, headers=headers)
    assert r.status_code == 201, r.text
    uid = r.json()["upload_id"]
    r = client.put(f"/v1/uploads/{uid}/content", content=path.read_bytes(), headers=headers)
    assert r.status_code == 200, r.text
    r = client.post(f"/v1/uploads/{uid}/finalize", headers=headers)
    assert r.status_code == 200, r.text
    return uid, r.json()
