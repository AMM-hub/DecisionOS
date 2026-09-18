"""Pre-parse quarantine scanning (spec §8.2).

Verdicts: clean | rejected. Never imply antivirus completeness — this is a
hostile-content screen within resource limits, one layer of defense.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field

from .config import LIMITS

CSV_SIGNATURES = (b"",)  # CSV has no magic; content sniffing below
XLSX_MAGIC = b"PK\x03\x04"


@dataclass
class ScanResult:
    verdict: str  # clean | rejected
    reasons: list[str] = field(default_factory=list)
    detected_format: str | None = None


def sniff_format(filename: str, data: bytes) -> str | None:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in LIMITS.allowed_extensions:
        return None
    if ext == "xlsx":
        if not data.startswith(XLSX_MAGIC):
            return None
        return "xlsx"
    if data.startswith(b"\xd0\xcf\x11\xe0"):  # legacy OLE .xls disguised as .csv/xlsx
        return None
    return "csv"


def scan(filename: str, data: bytes) -> ScanResult:
    reasons: list[str] = []
    if len(data) > LIMITS.max_upload_bytes:
        return ScanResult("rejected", [f"size {len(data)} exceeds limit {LIMITS.max_upload_bytes}"])

    fmt = sniff_format(filename, data)
    if fmt is None:
        return ScanResult("rejected", ["file signature/MIME does not match an allowlisted format"])

    if fmt == "xlsx":
        try:
            with zipfile.ZipFile(__import__("io").BytesIO(data)) as zf:
                total = sum(i.file_size for i in zf.infolist())
                compressed = max(1, len(data))
                if total / compressed > LIMITS.max_decompression_ratio and total > 10_000_000:
                    return ScanResult("rejected", [f"decompression ratio {total / compressed:.1f} exceeds bomb guard"])
                names = zf.namelist()
                if any(n.endswith(".bin") or "vbaProject" in n for n in names):
                    return ScanResult("rejected", ["macro/VBA content is never accepted"])
        except zipfile.BadZipFile:
            return ScanResult("rejected", ["corrupt archive"])

    return ScanResult("clean", [], fmt)


FORMULA_PREFIXES = ("=", "+", "-", "@")


def formula_risk_cells(text: str, sample_limit: int = 5000) -> list[str]:
    """Flag spreadsheet-formula-injection candidates for the export policy (§8.2)."""
    hits = []
    for i, line in enumerate(text.splitlines()[:sample_limit]):
        for cell in line.split(","):
            c = cell.strip().strip('"')
            if c.startswith(FORMULA_PREFIXES) and len(c) > 1 and any(ch in c for ch in "()|'"):
                hits.append(f"line {i + 1}: {c[:40]}")
    return hits
