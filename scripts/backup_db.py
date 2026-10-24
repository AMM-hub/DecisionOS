"""Create a verified, consistent snapshot of the analytics control database.

Uses SQLite ``VACUUM INTO`` (never a plain file copy), then re-opens the
snapshot and runs ``PRAGMA integrity_check`` and ``PRAGMA foreign_key_check``.
Writes a ``.sha256`` sidecar and a small ``.json`` manifest next to the
timestamped snapshot. Exits non-zero when the snapshot fails verification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _snapshot_path(out_dir: Path) -> Path:
    stamp = _timestamp()
    candidate = out_dir / f"control-{stamp}.sqlite3"
    counter = 1
    while candidate.exists():
        candidate = out_dir / f"control-{stamp}-{counter}.sqlite3"
        counter += 1
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify(snapshot: Path) -> dict[str, object]:
    conn = sqlite3.connect(snapshot)
    try:
        integrity_rows = conn.execute("PRAGMA integrity_check").fetchall()
        integrity = "; ".join(str(row[0]) for row in integrity_rows) or "empty"
        try:
            foreign_key_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
            foreign_key_check: object = "ok" if not foreign_key_rows else "violations"
            foreign_key_violations: int | None = len(foreign_key_rows)
        except sqlite3.Error as exc:
            foreign_key_check = f"unavailable: {exc}"
            foreign_key_violations = None
    finally:
        conn.close()
    return {
        "integrity_check": "ok" if integrity_rows == [("ok",)] else integrity,
        "foreign_key_check": foreign_key_check,
        "foreign_key_violations": foreign_key_violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up the DecisionOS control SQLite database.")
    parser.add_argument("--db", required=True, help="Path to control.sqlite3")
    parser.add_argument("--out", default="./var/backups", help="Directory for snapshots (default: ./var/backups)")
    args = parser.parse_args(argv)

    source = Path(args.db).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    if not source.is_file():
        print(f"backup failed: source database not found: {source}", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshot = _snapshot_path(out_dir)
    conn = sqlite3.connect(source)
    try:
        conn.execute("VACUUM INTO ?", (str(snapshot),))
    finally:
        conn.close()

    checks = _verify(snapshot)
    digest = _sha256(snapshot)
    sidecar = Path(f"{snapshot}.sha256")
    sidecar.write_text(f"{digest}  {snapshot.name}\n", encoding="utf-8")

    manifest = {
        "source": str(source),
        "snapshot": str(snapshot),
        "bytes": snapshot.stat().st_size,
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "sha256": digest,
        "checks": checks,
    }
    Path(f"{snapshot}.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    verified = checks["integrity_check"] == "ok" and checks["foreign_key_violations"] in (0, None)
    print(json.dumps({"snapshot": str(snapshot), "verified": verified, "checks": checks}))
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
