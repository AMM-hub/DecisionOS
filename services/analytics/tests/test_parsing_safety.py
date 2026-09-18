from __future__ import annotations

from pathlib import Path

import pytest

from decisionos_analytics.parsing import parse_csv
from decisionos_analytics.scanning import scan

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "support-tickets" / "data"
DIRTY = (FIXTURES / "adversarial" / "tickets_cases_dirty.csv").read_bytes()


def test_leading_zero_identifiers_preserved():  # QA-001
    out = parse_csv(DIRTY)
    col = out.frame["case_id"]
    assert col.dtype == out.frame.schema["case_id"]
    assert "00123" in col.to_list()
    assert "999999999999999999999" in col.to_list()  # long numeric-looking string stays text


def test_ambiguous_date_requires_parsing_rule():  # QA-002
    out = parse_csv(DIRTY)
    assert any("ambiguous" in i for i in out.issues)
    assert out.dialect_confidence == "needs_confirmation"


def test_malformed_rows_rejected_and_counted():
    out = parse_csv(DIRTY)
    assert len(out.rejected_rows) == 1
    assert out.rejected_rows[0]["line"] == 7  # wrong field count
    assert out.row_count == 6  # reconciles: 7 data lines - 1 rejected


def test_disguised_file_rejected_by_signature():
    r = scan("evil.csv", b"\xd0\xcf\x11\xe0rest of OLE header payload")
    assert r.verdict == "rejected"


def test_extension_allowlist():
    assert scan("payload.exe", b"MZ\x90\x00").verdict == "rejected"


def test_size_limit():
    from decisionos_analytics.config import LIMITS
    big = b"a" * (LIMITS.max_upload_bytes + 1)
    assert scan("big.csv", big).verdict == "rejected"


def test_row_limit_aborts():
    from decisionos_analytics.config import LIMITS
    header = "a,b\n"
    body = "\n".join(f"{i},{i}" for i in range(50))
    with pytest.raises(Exception):
        parse_csv((header + body).encode(), max_rows=10)
