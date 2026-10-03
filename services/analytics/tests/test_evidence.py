"""WP-01 Evidence Artifact Engine Unit & Security Tests."""

from __future__ import annotations

import json
import pytest
import polars as pl
from fastapi.testclient import TestClient

from decisionos_analytics.api import create_app
from decisionos_analytics.evidence import compute_canonical_digest
from decisionos_analytics.store import new_id, now_iso


@pytest.fixture
def test_app(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    return client, app.state.store, app.state.objects


def test_canonical_digest_determinism():
    data1 = [{"a": 1, "b": "test"}, {"a": 2, "b": "sample"}]
    data2 = [{"b": "test", "a": 1}, {"b": "sample", "a": 2}]
    digest1 = compute_canonical_digest(data1)
    digest2 = compute_canonical_digest(data2)
    assert digest1 == digest2
    assert len(digest1) == 64


def test_evidence_api_flow_and_tenant_isolation(test_app):
    client, store, objects = test_app
    headers_alpha = {"X-Tenant": "tenant_alpha", "X-User": "alpha.manager"}
    headers_beta = {"X-Tenant": "tenant_beta", "X-User": "beta.manager"}

    # 1. Setup tenant_alpha investigation
    inv_resp = store.conn.execute(
        """INSERT INTO investigation (
            tenant_id, id, title, question, source_type, owner, created_by, created_at, updated_at
        ) VALUES ('tenant_alpha', 'inv-101', 'ICU Surge', 'Why surge?', 'ad_hoc', 'alpha.manager', 'alpha.manager', ?, ?)""",
        (now_iso(), now_iso())
    )
    store.conn.commit()

    # 2. Setup certified metric & published dataset revision in store for tenant_alpha
    dataset_id = "ds-icu"
    store.conn.execute(
        "INSERT INTO dataset (tenant_id, id, workspace_id, name, published_revision, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("tenant_alpha", dataset_id, "ws-support-ops", "ICU Data", 1, now_iso())
    )
    import io
    buf = io.BytesIO()
    df = pl.DataFrame({"timestamp": ["2024-01-01T10:00:00Z"], "occupancy": [85]})
    df.write_parquet(buf)
    obj_res = objects.put_revision_object("tenant_alpha", dataset_id, 1, "rev-1.parquet", buf.getvalue())
    obj_key = obj_res["key"]

    manifest = {"objects": [{"key": obj_key}]}
    store.conn.execute(
        "INSERT INTO dataset_revision (tenant_id, dataset_id, revision, state, manifest, row_count, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("tenant_alpha", dataset_id, 1, "published", json.dumps(manifest), 1, now_iso())
    )
    store.conn.execute(
        "INSERT INTO definition (tenant_id, id, kind, created_by) VALUES (?, ?, ?, ?)",
        ("tenant_alpha", "m_occupancy", "count", "alpha.manager")
    )
    defn_content = {
        "metric_id": "m_occupancy",
        "name": "ICU Occupancy",
        "kind": "count",
        "expression": {"kind": "count", "predicates": []},
        "eligibility": [],
        "time_basis": "timestamp",
        "timezone": "UTC",
        "dataset_id": dataset_id,
    }
    store.conn.execute(
        "INSERT INTO definition_version (tenant_id, definition_id, version, content, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("tenant_alpha", "m_occupancy", 1, json.dumps(defn_content), "alpha.manager", now_iso())
    )
    store.conn.execute(
        """INSERT INTO definition_publication (
            tenant_id, definition_id, version, semantic_release_id, effective_from, published_at, approved_by, change_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("tenant_alpha", "m_occupancy", 1, "rel-1", now_iso(), now_iso(), "alpha.manager", "initial")
    )
    store.conn.commit()

    # 3. Create Evidence via API
    resp = client.post(
        "/v1/evidence",
        headers=headers_alpha,
        json={
            "investigation_id": "inv-101",
            "metric_id": "m_occupancy",
            "evidence_type": "observed",
            "support_status": "supporting",
            "query_params": {
                "window": {"start": "2024-01-01T00:00:00Z", "end": "2024-01-02T00:00:00Z"}
            }
        }
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["artifact_id"].startswith("ev-")
    assert data["digest_verified"] is True
    assert data["dataset_revision"] == 1
    assert data["metric_id"] == "m_occupancy"
    ev_id = data["artifact_id"]

    # 4. Get Evidence via API (Same Tenant)
    get_resp = client.get(f"/v1/evidence/{ev_id}", headers=headers_alpha)
    assert get_resp.status_code == 200
    assert get_resp.json()["artifact_id"] == ev_id

    # 5. Cross-tenant retrieval attempt by Tenant Beta (returns 404)
    beta_get = client.get(f"/v1/evidence/{ev_id}", headers=headers_beta)
    assert beta_get.status_code == 404

    # 6. Cross-tenant creation attempt by Tenant Beta referencing Alpha investigation
    beta_create = client.post(
        "/v1/evidence",
        headers=headers_beta,
        json={
            "investigation_id": "inv-101",
            "metric_id": "m_occupancy"
        }
    )
    assert beta_create.status_code == 404
