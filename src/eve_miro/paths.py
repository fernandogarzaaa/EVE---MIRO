"""First-party in-tree engine locations for this combination repo.

``src/eve_miro/paths.py`` → parents[2] is the repository root (``eve-miro/``).
MiroFish and EVE live in that root; they are not GitHub URL dependencies.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p


MIROFISH_ROOT = REPO_ROOT / "mirofish"
EVE_ROOT = REPO_ROOT / "eve"


def mirofish_root() -> Path:
    """In-tree MiroFish root; ``MIROFISH_ROOT`` env overrides the default."""
    return _env_path("MIROFISH_ROOT", MIROFISH_ROOT)


def eve_root() -> Path:
    """In-tree EVE root; ``EVE_ROOT`` env overrides the default."""
    return _env_path("EVE_ROOT", EVE_ROOT)


def engines_mode() -> str:
    """``in-tree`` (default, fail closed) or ``stub`` (pytest / offline).

    Unset ``EVE_MIRO_ENGINES`` means in-tree for API/closed-loop. Pytest
    ``conftest.py`` forces ``stub`` so unit tests stay offline.
    """
    raw = os.environ.get("EVE_MIRO_ENGINES", "in-tree").strip().lower().replace("_", "-")
    if raw in {"stub", "stubs"}:
        return "stub"
    return "in-tree"


def fail_closed() -> bool:
    """True when missing keys / HTTP / CLI failure must raise, not stub."""
    return engines_mode() != "stub"
