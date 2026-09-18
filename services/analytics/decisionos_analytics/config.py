"""Resource and safety limits for bounded workers (spec §8.2, §28)."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Limits:
    max_upload_bytes: int = 100 * 1024 * 1024
    max_rows: int = 2_000_000
    max_columns: int = 500
    max_cell_len: int = 32_767
    max_decompression_ratio: float = 50.0  # zip-bomb guard for xlsx
    max_parse_seconds: float = 120.0
    allowed_extensions: tuple[str, ...] = ("csv", "xlsx")
    allowed_encodings: tuple[str, ...] = ("utf-8-sig", "utf-8", "utf-16", "cp1256", "iso-8859-1")
    max_key_candidate_width: int = 2
    max_key_candidates: int = 25


LIMITS = Limits()
