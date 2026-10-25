from __future__ import annotations

import io

from openpyxl import Workbook

from conftest import upload_and_finalize


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Tickets"
    sheet.append(["Quarterly export"])
    sheet.append(["id", "region", "amount"])
    sheet.append([1, "north", 10.5])
    sheet.append([2, "south", 20])
    sheet.append([3, "north", 30])
    sheet.append([None, None, None])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_xlsx_parses_with_header_detection(client, alpha_headers):
    data = _workbook_bytes()
    upload_id, finalized = upload_and_finalize(
        client, alpha_headers, _write_tmp(data), "tickets.xlsx"
    )
    assert finalized["status"] == "scanned"
    assert finalized["dataset_id"]

    preview = client.get(f"/v1/uploads/{upload_id}/preview", headers=alpha_headers)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["detected"]["format"] == "xlsx"
    assert body["detected"]["header_row"] == 2
    assert body["row_count"] == 3
    assert [column["name"] for column in body["columns"]] == ["id", "region", "amount"]
    assert body["columns"][0]["inferred_type"] == "integer"
    assert body["columns"][2]["inferred_type"] == "float"


def test_truncated_xlsx_archive_is_parse_failed(client, alpha_headers):
    response = client.post(
        "/v1/uploads",
        json={"filename": "broken.xlsx", "size_bytes": 12, "workspace_id": "ws-support-ops"},
        headers=alpha_headers,
    )
    assert response.status_code == 201
    upload_id = response.json()["upload_id"]
    assert client.put(
        f"/v1/uploads/{upload_id}/content", content=b"PK\x03\x04broken", headers=alpha_headers
    ).status_code == 200
    finalized = client.post(f"/v1/uploads/{upload_id}/finalize", headers=alpha_headers)
    assert finalized.status_code == 422, finalized.text
    assert finalized.json()["code"] == "parse_failed"


def test_legacy_xls_is_explicitly_refused(client, alpha_headers):
    response = client.post(
        "/v1/uploads",
        json={"filename": "legacy.csv", "size_bytes": 16, "workspace_id": "ws-support-ops"},
        headers=alpha_headers,
    )
    assert response.status_code == 201
    upload_id = response.json()["upload_id"]
    assert client.put(
        f"/v1/uploads/{upload_id}/content",
        content=b"\xd0\xcf\x11\xe0legacy-xls-bytes",
        headers=alpha_headers,
    ).status_code == 200
    finalized = client.post(f"/v1/uploads/{upload_id}/finalize", headers=alpha_headers)
    assert finalized.status_code == 422, finalized.text
    assert finalized.json()["code"] == "unsupported_format"


def _write_tmp(data: bytes):
    import tempfile
    from pathlib import Path

    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    handle.write(data)
    handle.close()
    return Path(handle.name)
