"""Bounded, safe CSV parsing with preview (spec §8.2, §9.1).

Hard rules implemented here:
- Identifiers and leading zeros are preserved: id-like columns stay strings.
- Ambiguous dates are NOT silently parsed; they are flagged for confirmation.
- Rows violating the column contract are rejected separately and counted.
- Size / row / column / cell-length / runtime limits abort with an explicit error.
"""

from __future__ import annotations

import csv as _csv
import io
import re
import time
from dataclasses import dataclass
from datetime import date, datetime

import polars as pl

from .config import LIMITS

ID_LIKE = re.compile(r"(_id|_code|id)$")
ISO_8601 = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$")
AMBIGUOUS_SLASH_DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}")
LEADING_ZERO = re.compile(r"^0\d")

XLSX_MAGIC = b"PK\x03\x04"
LEGACY_XLS_MAGIC = b"\xd0\xcf\x11\xe0"


class ParseAbort(Exception):
    pass


class ParseError(ParseAbort):
    """A bounded parse failure with a stable error code."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def detect_format(filename: str, data: bytes) -> str:
    """Route by extension *and* magic bytes; never trust the extension alone."""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if data.startswith(LEGACY_XLS_MAGIC):
        raise ParseError(
            "unsupported_format",
            "Legacy .xls workbooks are not supported; export to .xlsx or .csv.",
        )
    if data.startswith(XLSX_MAGIC):
        return "xlsx"
    if extension == "xlsx":
        raise ParseError("parse_failed", "The uploaded workbook is not a valid xlsx archive.")
    if extension in ("csv", "txt", ""):
        return "csv"
    raise ParseError("unsupported_format", f"Unsupported file format '.{extension}'.")


@dataclass
class ParseOutcome:
    frame: pl.DataFrame
    detected_encoding: str
    detected_delimiter: str
    header_row: int
    dialect_confidence: str
    columns: list[dict]
    rejected_rows: list[dict]
    issues: list[str]
    row_count: int


def detect_encoding(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "utf-16", "cp1256", "iso-8859-1"):
        try:
            data.decode(enc)
            if enc == "iso-8859-1":
                return enc  # always decodes; uncertain -> caller must confirm
            return enc
        except UnicodeDecodeError:
            continue
    raise ParseAbort("no allowlisted encoding could decode the file")


def detect_delimiter(text: str) -> str:
    first = text.splitlines()[0] if text.splitlines() else ""
    counts = {d: first.count(d) for d in [",", ";", "\t"]}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def _column_policy(name: str, values: list[str]) -> tuple[pl.DataType, str | None]:
    """Return storage dtype + issue note. Identifiers stay strings (QA-001)."""
    nonnull = [v for v in values if v != ""]
    token_like = [v for v in nonnull[:200] if re.match(r"^[0-9A-Za-z_-]+$", v)]
    if ID_LIKE.search(name.lower()) or (token_like and any(LEADING_ZERO.match(v) for v in token_like) and len(token_like) == len(nonnull[:200])):
        return pl.Utf8, None
    if not nonnull:
        return pl.Utf8, None
    if all(ISO_8601.match(v) for v in nonnull[:200]):
        return pl.Utf8, None  # parsed later under an explicit timezone policy
    if all(AMBIGUOUS_SLASH_DATE.match(v) for v in nonnull[:200]) or any(AMBIGUOUS_SLASH_DATE.match(v) for v in nonnull[:200]):
        return pl.Utf8, f"column '{name}' contains DD/MM vs MM/DD ambiguous dates; explicit parsing rule required (QA-002)"
    if all(re.match(r"^-?\d+$", v) and len(v) <= 15 for v in nonnull[:200]):
        return pl.Int64, None
    if all(re.match(r"^-?[\d.]+$", v) for v in nonnull[:200]):
        return pl.Float64, None
    return pl.Utf8, None


def parse_csv(data: bytes, max_rows: int | None = None, deadline_s: float | None = None) -> ParseOutcome:
    t0 = time.monotonic()
    deadline = deadline_s or LIMITS.max_parse_seconds
    encoding = detect_encoding(data)
    text = data.decode(encoding)
    delimiter = detect_delimiter(text)

    reader = _csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        raise ParseAbort("empty file")
    header = [h.strip().strip('"') for h in rows[0]]
    if len(header) > LIMITS.max_columns:
        raise ParseAbort(f"column count {len(header)} exceeds limit")

    accepted: list[list[str]] = []
    rejected: list[dict] = []
    limit = max_rows or LIMITS.max_rows
    for lineno, row in enumerate(rows[1:], start=2):
        if time.monotonic() - t0 > deadline:
            raise ParseAbort("parse runtime limit exceeded")
        if len(accepted) >= limit:
            raise ParseAbort(f"row limit {limit} exceeded")
        if len(row) != len(header):
            rejected.append({"line": lineno, "reason": f"expected {len(header)} fields, got {len(row)}"})
            continue
        if any(len(c) > LIMITS.max_cell_len for c in row):
            rejected.append({"line": lineno, "reason": "cell exceeds max length"})
            continue
        accepted.append(row)

    issues: list[str] = []
    columns_meta = []
    series = {}
    for ci, name in enumerate(header):
        vals = [r[ci] for r in accepted]
        dtype, issue = _column_policy(name, vals)
        if issue:
            issues.append(issue)
        nn = [v for v in vals if v != ""]
        inferred = {pl.Utf8: "string", pl.Int64: "integer", pl.Float64: "float"}[dtype]
        try:
            s = pl.Series(name, [int(v) if v != "" else None for v in vals] if dtype == pl.Int64 else ([float(v) if v != "" else None for v in vals] if dtype == pl.Float64 else vals), dtype=dtype)
        except Exception as exc:  # noqa: BLE001 - coercion failure keeps the column as text and records the issue
            issues.append(f"column '{name}' kept as text: {exc}")
            s = pl.Series(name, vals, dtype=pl.Utf8)
            inferred = "string"
        series[name] = s
        sample = list(dict.fromkeys(v for v in vals if v != ""))[:3]
        columns_meta.append({"name": name, "inferred_type": inferred, "null_rate": round(1 - len(nn) / max(1, len(vals)), 4), "sample": sample})

    frame = pl.DataFrame(series)
    dup_labels = [n for n in set(header) if header.count(n) > 1]
    if dup_labels:
        issues.append(f"duplicate column labels need mapping, not silent flattening: {dup_labels}")

    return ParseOutcome(
        frame=frame,
        detected_encoding=encoding,
        detected_delimiter=delimiter,
        header_row=1,
        dialect_confidence="needs_confirmation" if (encoding == "iso-8859-1" or any("ambiguous" in i for i in issues)) else "high",
        columns=columns_meta,
        rejected_rows=rejected,
        issues=issues,
        row_count=frame.height,
    )


def _coerce_xlsx_cell(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


def _xlsx_frame(rows: list[list], header: list[str]) -> pl.DataFrame:
    series: dict[str, pl.Series] = {}
    for index, name in enumerate(header):
        values = [row[index] if index < len(row) else None for row in rows]
        nonnull = [value for value in values if value is not None and value != ""]
        if nonnull and all(isinstance(value, int) for value in nonnull):
            dtype = pl.Int64
        elif nonnull and all(isinstance(value, (int, float)) for value in nonnull):
            dtype = pl.Float64
        else:
            dtype = pl.Utf8
        if dtype == pl.Utf8:
            cleaned = [None if value is None or value == "" else str(value) for value in values]
        else:
            cleaned = [None if value is None or value == "" else value for value in values]
        series[name] = pl.Series(name, cleaned, dtype=dtype)
    return pl.DataFrame(series)


def parse_xlsx(
    data: bytes,
    sheet_name: str | None = None,
    max_rows: int | None = None,
    deadline_s: float | None = None,
) -> ParseOutcome:
    """Read the first (or named) worksheet with openpyxl in read-only mode."""
    t0 = time.monotonic()
    deadline = deadline_s or LIMITS.max_parse_seconds
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ParseError("unsupported_format", "xlsx support is not installed.") from exc

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - any workbook read failure is a 422
        raise ParseError("parse_failed", "The workbook could not be parsed.") from exc

    try:
        if not workbook.sheetnames:
            raise ParseError("parse_failed", "The workbook contains no worksheets.")
        if sheet_name is not None:
            if sheet_name not in workbook.sheetnames:
                raise ParseError("parse_failed", f"Worksheet '{sheet_name}' was not found.")
            worksheet = workbook[sheet_name]
        else:
            worksheet = workbook.worksheets[0]

        raw_rows: list[list] = []
        header: list[str] | None = None
        header_row_number = 0
        for row_number, row in enumerate(worksheet.iter_rows(values_only=True), start=1):
            if time.monotonic() - t0 > deadline:
                raise ParseError("parse_failed", "Workbook parsing exceeded the runtime limit.")
            cells = [_coerce_xlsx_cell(value) for value in row]
            while cells and cells[-1] is None:
                cells.pop()
            if header is None:
                nonempty = [cell for cell in cells if cell is not None and str(cell).strip() != ""]
                if len(nonempty) >= 2:
                    header = []
                    for index, cell in enumerate(cells):
                        name = "" if cell is None else str(cell).strip()
                        header.append(name or f"column_{index + 1}")
                    header_row_number = row_number
                continue
            if len(cells) > len(header):
                cells = cells[: len(header)]
            cells.extend([None] * (len(header) - len(cells)))
            raw_rows.append(cells)
            limit = max_rows or LIMITS.max_rows
            if len(raw_rows) > limit:
                raise ParseError("parse_failed", f"Row limit {limit} exceeded.")

        if header is None:
            raise ParseError("parse_failed", "No header row with at least two populated cells was found.")

        while raw_rows and all(
            cell is None or str(cell).strip() == "" for cell in raw_rows[-1]
        ):
            raw_rows.pop()

        frame = _xlsx_frame(raw_rows, header)
        columns_meta = []
        for name in header:
            column = frame[name]
            nulls = int(column.is_null().sum() + (column == "").sum() if column.dtype == pl.Utf8 else column.is_null().sum())
            sample_values = [str(value) for value in column.drop_nulls().head(3).to_list()]
            inferred = {pl.Utf8: "string", pl.Int64: "integer", pl.Float64: "float"}[column.dtype]
            columns_meta.append(
                {
                    "name": name,
                    "inferred_type": inferred,
                    "null_rate": round(nulls / max(1, frame.height), 4),
                    "sample": sample_values,
                }
            )

        issues = []
        duplicate_labels = sorted({name for name in header if header.count(name) > 1})
        if duplicate_labels:
            issues.append(f"duplicate column labels need mapping, not silent flattening: {duplicate_labels}")

        return ParseOutcome(
            frame=frame,
            detected_encoding="xlsx",
            detected_delimiter="",
            header_row=header_row_number,
            dialect_confidence="high",
            columns=columns_meta,
            rejected_rows=[],
            issues=issues,
            row_count=frame.height,
        )
    finally:
        workbook.close()


def parse_file(
    filename: str,
    data: bytes,
    max_rows: int | None = None,
    deadline_s: float | None = None,
) -> ParseOutcome:
    fmt = detect_format(filename, data)
    if fmt == "xlsx":
        return parse_xlsx(data, max_rows=max_rows, deadline_s=deadline_s)
    return parse_csv(data, max_rows=max_rows, deadline_s=deadline_s)
