"""File-backed JSON cache for re-runnable ingestion downloads.

Per the data-ingest spec:
- `raw/` supports idempotent re-runs without re-fetching.
- Cache content key is the upstream URL.
- Files land under `RAW_CACHE_DIR` (default: `data/raw/`).

Implementation notes:
- Atomic writes via tmp file + os.replace to survive crashed runs.
- Corrupt cache files are treated as misses (caller re-fetches and overwrites).
- Filenames are SHA-256(url) so URL syntax is opaque to the filesystem.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class RawCache:
    """Small content-addressed JSON cache."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        # Two-level fan-out keeps directory listings small for big corpora.
        return self._root / digest[:2] / digest[2:4] / f"{digest}.json"

    def get(self, url: str) -> Any | None:
        fp = self._path_for(url)
        if not fp.exists():
            return None
        try:
            return json.loads(fp.read_text())
        except (json.JSONDecodeError, OSError):
            # Corrupt cache file — treat as miss; caller will overwrite on put().
            return None

    def put(self, url: str, payload: Any) -> None:
        fp = self._path_for(url)
        fp.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write via tmp + replace so crashed runs don't leave half-files.
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=fp.parent,
            delete=False,
            suffix=".tmp",
        ) as tmp:
            json.dump(payload, tmp, ensure_ascii=False)
            tmp_path = tmp.name
        os.replace(tmp_path, fp)
