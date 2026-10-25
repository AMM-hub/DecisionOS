"""Resource and safety limits for bounded workers (spec §8.2, §28)."""

import os
from dataclasses import dataclass
from pathlib import Path

# services/analytics — the root every relative runtime path is anchored to.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def resolve_data_dir(explicit: str | Path | None = None) -> Path:
    """Absolute data directory, identical from any working directory.

    A relative ``DECISIONOS_DATA_DIR`` used to resolve against the process CWD,
    so the API (started in services/analytics) and the worker (started
    elsewhere) silently opened *different* SQLite files: the API queued a run
    into one database and the worker polled the other, reported "idle", and the
    run stayed `queued` forever. Anchor relative paths to the package root and
    always hand back an absolute path.
    """
    raw: str | Path = (
        explicit if explicit is not None else os.environ.get("DECISIONOS_DATA_DIR", "./var/worker")
    )
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PACKAGE_ROOT / path
    return path.resolve()


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
