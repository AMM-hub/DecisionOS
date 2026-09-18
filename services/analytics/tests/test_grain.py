from __future__ import annotations

from pathlib import Path

from decisionos_analytics.grain import grain_candidates, relationship_profile
from decisionos_analytics.parsing import parse_csv

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "support-tickets" / "data"


def _frame(p: Path):
    return parse_csv(p.read_bytes()).frame


def test_clean_cases_file_proves_case_grain():
    cands = grain_candidates(_frame(FIXTURES / "tenant_alpha" / "tickets_cases.csv"))
    case_id = next(c for c in cands if c["key_columns"] == ["case_id"])
    assert case_id["unique_over_full_data"] is True
    assert case_id["null_components"] == 0


def test_events_file_grain_is_event_not_case():  # QA-006 pattern
    frame = _frame(FIXTURES / "tenant_alpha" / "ticket_events.csv")
    cands = grain_candidates(frame)
    by_col = {tuple(c["key_columns"]): c for c in cands}
    assert by_col[("event_id",)]["unique_over_full_data"] is True
    # repeated case_id in status history is expected, not a duplicate-case defect (§33.1)
    assert by_col[("case_id",)]["unique_over_full_data"] is False


def test_dirty_file_grain_cannot_be_proven():  # QA-005
    cands = grain_candidates(_frame(FIXTURES / "adversarial" / "tickets_cases_dirty.csv"))
    case_id = next(c for c in cands if c["key_columns"] == ["case_id"])
    assert case_id["unique_over_full_data"] is False
    assert case_id["null_components"] >= 1
    assert any(d["occurrences"] >= 2 for d in case_id["duplicate_examples"])


def test_relationship_profile_one_to_many():
    cases = _frame(FIXTURES / "tenant_alpha" / "tickets_cases.csv")
    events = _frame(FIXTURES / "tenant_alpha" / "ticket_events.csv")
    prof = relationship_profile(cases, events, "case_id")
    assert prof["left_unique"] is True
    assert prof["right_max_fanout"] > 1
    assert prof["unmatched_right_rate"] == 0.0
