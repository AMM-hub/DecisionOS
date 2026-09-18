"""Local object store emulation with quarantine / raw-retention / immutable revision zones.

Paths encode authorization zones, but per spec §21.2 a path prefix is NOT
authorization — every access goes through the tenant-scoped store layer.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        for zone in ("quarantine", "raw-retention", "revisions", "published"):
            (self.root / zone).mkdir(parents=True, exist_ok=True)

    def _safe(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("path traversal denied")
        return p

    def put_quarantine(self, key: str, data: bytes) -> str:
        target = self._safe(f"quarantine/{key}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def get_quarantine(self, key: str) -> bytes:
        return self._safe(f"quarantine/{key}").read_bytes()

    def retain_raw(self, quarantine_key: str) -> str:
        """Preserve raw uploaded bytes until authorized retention expires (§8.2)."""
        src = self._safe(f"quarantine/{quarantine_key}")
        dest = self._safe(f"raw-retention/{quarantine_key}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return str(dest.relative_to(self.root)).replace("\\", "/")

    def put_revision_object(self, tenant_id: str, dataset_id: str, revision: int, name: str, data: bytes) -> dict:
        """Attempt objects are written to private immutable paths before publication (§8.5)."""
        key = f"revisions/{tenant_id}/{dataset_id}/{revision}/{name}"
        target = self._safe(key)
        if target.exists():
            raise FileExistsError("revision objects are immutable")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"key": key, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    def get_revision_object(self, key: str) -> bytes:
        return self._safe(key).read_bytes()

    def delete_quarantine(self, key: str) -> None:
        p = self._safe(f"quarantine/{key}")
        p.unlink(missing_ok=True)
