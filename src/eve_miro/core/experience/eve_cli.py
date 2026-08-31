from __future__ import annotations

import os
from pathlib import Path

from eve_miro.errors import EngineNotConfigured
from eve_miro.paths import eve_root


def _env(name: str):
    v = os.environ.get(name, "").strip()
    return v or None


def eve_trajectory_command(*, bin_path: str | None = None) -> list:
    root = eve_root()
    dist_main = root / "dist" / "cli" / "main.js"
    bin_js = Path(bin_path) if bin_path else (root / "bin" / "eve.js")
    src_main = root / "src" / "cli" / "main.ts"
    modules = root / "node_modules"
    explicit = bin_path or _env("EVE_BIN")
    if explicit:
        return [str(explicit), "trajectory", "--stdin"]
    if dist_main.is_file() and bin_js.is_file():
        return ["node", str(bin_js), "trajectory", "--stdin"]
    if modules.is_dir() and src_main.is_file():
        return ["npx", "tsx", str(src_main), "trajectory", "--stdin"]
    raise EngineNotConfigured("EVE CLI is not built")
