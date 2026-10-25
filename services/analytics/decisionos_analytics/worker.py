"""DB-backed ingestion worker.

Usage:
    python -m decisionos_analytics.worker --once
    python -m decisionos_analytics.worker --poll --interval 2

The worker resolves the same data directory as the API, applies migrations at
boot, and never raises an unhandled exception from a run: failures are recorded
on the run row and reported as structured log lines.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from .ai import crypto
from .config import resolve_data_dir
from .ingestion.jobs import run_pending
from .objectstore import LocalObjectStore
from .store import Store


def _data_dir() -> Path:
    return resolve_data_dir()


def _worker_id() -> str:
    return os.environ.get("DECISIONOS_WORKER_ID", "").strip() or f"worker-{os.getpid()}"


def _log(event: str, **fields) -> None:
    payload = {"event": event, "worker_id": _worker_id(), **fields}
    print(json.dumps(payload, default=str), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="decisionos-ingest-worker")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Claim and run at most one queued run, then exit.")
    mode.add_argument("--poll", action="store_true", help="Loop forever, polling for queued runs.")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between polls (default 2).")
    parser.add_argument("--limit", type=int, default=1, help="Runs to claim per poll (default 1).")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    crypto.configure(data_dir)

    store = Store(data_dir / "control.sqlite3")
    objects = LocalObjectStore(data_dir / "objects")
    # Log the master-key fingerprint: a worker started with a different
    # DECISIONOS_SECRET_KEY than the API cannot decrypt stored connector
    # credentials, and the only symptom is "credential could not be decrypted"
    # at ingest time. One shared fingerprint makes that mismatch obvious.
    _log(
        "worker.started",
        data_dir=str(data_dir),
        objects=str(objects.root),
        key_fingerprint=crypto.key_fingerprint(),
        mode="poll" if args.poll else "once",
    )

    if args.once or not args.poll:
        executed = run_pending(store, max(1, args.limit))
        _log("worker.idle" if executed == 0 else "worker.completed", executed=executed)
        store.close()
        return 0

    try:
        while True:
            executed = run_pending(store, max(1, args.limit))
            if executed == 0:
                _log("worker.idle")
                time.sleep(max(0.1, args.interval))
            else:
                _log("worker.completed", executed=executed)
    except KeyboardInterrupt:
        _log("worker.stopped")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
