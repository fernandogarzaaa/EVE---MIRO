"""MinIO/S3 object helper. Optional; traces default to local data/traces/."""

from __future__ import annotations

import os
from pathlib import Path


def traces_dir() -> Path:
    raw = os.environ.get("EVE_MIRO_TRACES", "")
    path = Path(raw) if raw else Path("/workspace/eve-miro/data/traces")
    path.mkdir(parents=True, exist_ok=True)
    return path


def put_bytes(key: str, data: bytes) -> Path:
    """Local stand-in for MinIO put. Compose ships MinIO for later object storage."""
    dest = traces_dir() / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest
