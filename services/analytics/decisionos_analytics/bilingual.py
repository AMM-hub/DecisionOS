"""M6 — Arabic/English Bilingual Search & Normalization (spec §27).

Search normalization that preserves original text while adding bilingual
indexes. Arabic morphology handling, code-switching support, and locale-
aware search without aggressive normalization.
"""

from __future__ import annotations

import re
import unicodedata


_ARABIC_NORMALIZE = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا",  # hamza variants → alif
    "ة": "ه",  # tāʼ marbūṭa → hāʼ
    "ى": "ي",  # alif maqṣūra → yāʼ
    "ئ": "ي",  # hamza on yāʼ → yāʼ
    "ؤ": "و",  # hamza on wāw → wāw
})

_ARABIC_KASHIDA = re.compile(r"ـ+")  # tatweel/kashida


def normalize_search(text: str) -> str:
    """Normalize text for search indexing.

    Preserves original characters while producing a normalized form
    that matches across common Arabic spelling variants.
    """
    if not text:
        return text

    # NFC normalize first
    nfc = unicodedata.normalize("NFC", text)

    # Remove kashida (tatweel)
    no_kashida = _ARABIC_KASHIDA.sub("", nfc)

    # Normalize Arabic variants (works on single chars after NFC)
    normalized = no_kashida.translate(_ARABIC_NORMALIZE)

    # NFC again to recompose any decomposed chars
    normalized = unicodedata.normalize("NFC", normalized)

    # Lowercase for English portion
    normalized = normalized.lower()

    # Collapse whitespace
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized


def tokenize_bilingual(text: str) -> list[str]:
    """Tokenize text into meaningful search tokens.

    Preserves both Arabic and English tokens, handling common
    code-switching patterns.
    """
    normalized = normalize_search(text)
    # Split on non-alphanumeric (keep Arabic letters which are \w in Unicode)
    tokens = re.findall(r"[\w\u0600-\u06FF]+", normalized, re.UNICODE)
    return [t for t in tokens if len(t) >= 1]


def build_search_aliases(
    english_label: str,
    arabic_label: str | None = None,
    extra_terms: list[str] | None = None,
) -> dict:
    """Build a search alias structure with normalized forms.

    Returns dict with original terms and their normalized equivalents
    so search can match across languages.
    """
    aliases: dict[str, list[str]] = {
        "en": [english_label],
        "en_normalized": [normalize_search(english_label)],
        "ar": [],
        "ar_normalized": [],
        "combined": [],
    }

    if arabic_label:
        aliases["ar"] = [arabic_label]
        aliases["ar_normalized"] = [normalize_search(arabic_label)]

    # Build combined token set for broad matching
    all_terms = [english_label]
    if arabic_label:
        all_terms.append(arabic_label)
    if extra_terms:
        all_terms.extend(extra_terms)

    combined_tokens: set[str] = set()
    for term in all_terms:
        for token in tokenize_bilingual(term):
            combined_tokens.add(token)
            combined_tokens.add(normalize_search(token))

    aliases["combined"] = sorted(combined_tokens)
    return aliases


def search_match(query: str, aliases: dict) -> bool:
    """Check if a search query matches the aliases.

    Matches against original English, Arabic, and all normalized forms.
    """
    if not query:
        return True

    q_normalized = normalize_search(query)
    q_tokens = set(tokenize_bilingual(query))

    # Check direct matches against all alias fields
    for field in ("en", "ar", "en_normalized", "ar_normalized"):
        for alias_val in aliases.get(field, []):
            if q_normalized in normalize_search(alias_val):
                return True

    # Check token overlap
    combined_tokens = set(aliases.get("combined", []))
    if q_tokens & combined_tokens:
        return True

    return False


# ---------------------------------------------------------------------------
# Bilingual label support
# ---------------------------------------------------------------------------

BilingualLabel = dict[str, str]  # {"en": "...", "ar": "..."}


def make_label(en: str, ar: str | None = None) -> BilingualLabel:
    """Create a bilingual label tuple."""
    label: BilingualLabel = {"en": en}
    if ar:
        label["ar"] = ar
    return label


def get_label(label: BilingualLabel, locale: str = "en") -> str:
    """Get the appropriate label for the requested locale."""
    if locale == "ar" and "ar" in label:
        return label["ar"]
    return label.get("en", "")


# ---------------------------------------------------------------------------
# Common bilingual labels for the analytics domain
# ---------------------------------------------------------------------------

BILLINGUAL_METRIC_LABELS: dict[str, BilingualLabel] = {
    "metric-first-response-rate": make_label(
        "First Response Rate",
        "معدل الاستجابة الأولى",
    ),
    "metric-resolution-time": make_label(
        "Resolution Time (P50)",
        "متوسط وقت الحل",
    ),
    "metric-case-volume": make_label(
        "Case Volume",
        "حجم الحالات",
    ),
    "metric-backlog-age": make_label(
        "Backlog Age (P90)",
        "عمر المهام المتراكمة",
    ),
    "metric-escalation-rate": make_label(
        "Escalation Rate",
        "معدل التصعيد",
    ),
}

BILLINGUAL_DATASET_LABELS: dict[str, BilingualLabel] = {
    "support-tickets": make_label(
        "Support Tickets",
        "تذاكر الدعم",
    ),
}

BILLINGUAL_STATUS_LABELS: dict[str, BilingualLabel] = {
    "healthy": make_label("Healthy", "سليم"),
    "stale": make_label("Stale", "قديم"),
    "suspended": make_label("Suspended", "موقوف"),
    "unknown": make_label("Unknown", "غير معروف"),
    "open": make_label("Open", "مفتوح"),
    "acknowledged": make_label("Acknowledged", "مؤكد"),
    "investigating": make_label("Investigating", "قيد التحقيق"),
    "resolved": make_label("Resolved", "تم الحل"),
    "dismissed": make_label("Dismissed", "مهمل"),
    "published": make_label("Published", "منشور"),
    "approved": make_label("Approved", "معتمد"),
    "rejected": make_label("Rejected", "مرفوض"),
}