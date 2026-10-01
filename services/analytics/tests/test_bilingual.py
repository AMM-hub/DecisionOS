"""M6 — Arabic/English Bilingual tests (spec §27).

Tests for search normalization, bilingual label support, and search matching.
"""

from __future__ import annotations

import pytest
from decisionos_analytics.bilingual import (
    normalize_search,
    tokenize_bilingual,
    build_search_aliases,
    search_match,
    make_label,
    get_label,
    BILLINGUAL_METRIC_LABELS,
    BILLINGUAL_STATUS_LABELS,
)


class TestNormalizeSearch:
    """27.1 — Localization: search normalization preserves original text."""

    def test_basic_english(self):
        assert normalize_search("Hello World") == "hello world"

    def test_arabic_alif_variants(self):
        # أ إ آ should all normalize to ا
        a = normalize_search("أحمد")
        b = normalize_search("احمد")
        assert a == b
        c = normalize_search("إحمد")
        d = normalize_search("آحمد")
        assert c == d
        assert a == c

    def test_arabic_ta_marbuta(self):
        # ة → ه
        assert normalize_search("جامعة") == normalize_search("جامعه")

    def test_arabic_alif_maqsura(self):
        # ى → ي
        assert normalize_search("مستشفى") == normalize_search("مستشفي")

    def test_kashida_removed(self):
        assert normalize_search("جمــــيل") == normalize_search("جميل")

    def test_preserves_original_text(self):
        text = "معدل الاستجابة الأولى"
        normalized = normalize_search(text)
        # Arabic words should still be recognizable
        assert "معدل" in normalized
        # ة became ه after normalization, so الاستجابة → الاستجابه
        assert "الاستجابه" in normalized or "الاستجابة" in normalized

    def test_code_switching(self):
        text = "First Response Rate معدل الاستجابة"
        n = normalize_search(text)
        assert "first" in n
        assert "response" in n
        assert "rate" in n
        assert "معدل" in n
        # ة→ه after normalization
        assert "الاستجابه" in n or "الاستجابة" in n

    def test_whitespace_collapse(self):
        assert normalize_search("  hello   world  ") == "hello world"


class TestSearchAliases:
    """27.1 — Search alias construction."""

    def test_english_only(self):
        aliases = build_search_aliases("First Response Rate")
        assert "en" in aliases
        assert "ar" in aliases
        assert aliases["ar"] == []
        assert "first" in aliases["combined"]
        assert "response" in aliases["combined"]

    def test_bilingual(self):
        aliases = build_search_aliases(
            "First Response Rate",
            "معدل الاستجابة الأولى",
        )
        assert "ar" in aliases
        assert "معدل" in aliases["combined"]
        # ة→ه after normalization
        assert "الاستجابه" in aliases["combined"] or "الاستجابة" in aliases["combined"]

    def test_combined_tokens_include_normalized(self):
        aliases = build_search_aliases(
            "First Response Rate",
            "معدل الاستجابة الأولى",
        )
        # Normalized forms should be in combined
        assert "معدل" in aliases["combined"]


class TestSearchMatch:
    """27.1 — Search matching against bilingual labels."""

    def test_exact_english_match(self):
        aliases = {"en": ["First Response Rate"], "ar": []}
        assert search_match("First Response Rate", aliases) is True

    def test_partial_english_match(self):
        aliases = {"en": ["First Response Rate"], "ar": []}
        assert search_match("first", aliases) is True

    def test_arabic_match(self):
        aliases = {"en": ["First Response Rate"], "ar": ["معدل الاستجابة الأولى"]}
        assert search_match("معدل", aliases) is True

    def test_arabic_normalized_match(self):
        aliases = build_search_aliases("First Response Rate", "معدل الاستجابة الأولى")
        assert search_match("الاستجابه", aliases) is True  # ة→ه normalization

    def test_no_match_returns_false(self):
        aliases = {"en": ["First Response Rate"], "ar": []}
        assert search_match("nonexistent", aliases) is False

    def test_empty_query_matches_everything(self):
        aliases = {"en": ["Something"], "ar": []}
        assert search_match("", aliases) is True


class TestBilingualLabels:
    """27.1 — Bilingual label support."""

    def test_make_label(self):
        label = make_label("Hello", "مرحبا")
        assert label["en"] == "Hello"
        assert label["ar"] == "مرحبا"

    def test_get_label_english(self):
        label = make_label("Hello", "مرحبا")
        assert get_label(label, "en") == "Hello"

    def test_get_label_arabic(self):
        label = make_label("Hello", "مرحبا")
        assert get_label(label, "ar") == "مرحبا"

    def test_get_label_fallback(self):
        label = make_label("Hello")
        assert get_label(label, "ar") == "Hello"  # fallback to English

    def test_predefined_metric_labels(self):
        assert "metric-first-response-rate" in BILLINGUAL_METRIC_LABELS
        label = BILLINGUAL_METRIC_LABELS["metric-first-response-rate"]
        assert "معدل" in label["ar"]
        assert "Response" in label["en"]

    def test_predefined_status_labels(self):
        assert "healthy" in BILLINGUAL_STATUS_LABELS
        assert "سليم" in BILLINGUAL_STATUS_LABELS["healthy"]["ar"]
        assert "resolved" in BILLINGUAL_STATUS_LABELS
        assert "تم الحل" in BILLINGUAL_STATUS_LABELS["resolved"]["ar"]


class TestTokenizeBilingual:
    """27.1 — Tokenization of mixed-language text."""

    def test_english_tokens(self):
        tokens = tokenize_bilingual("First Response Rate")
        assert "first" in tokens
        assert "response" in tokens
        assert "rate" in tokens

    def test_arabic_tokens(self):
        tokens = tokenize_bilingual("معدل الاستجابة الأولى")
        assert "معدل" in tokens
        assert len(tokens) >= 3

    def test_mixed_tokens(self):
        tokens = tokenize_bilingual("metric القياس")
        assert "metric" in tokens
        assert "القياس" in tokens or "مقياس" in tokens

    def test_empty_text(self):
        assert tokenize_bilingual("") == []