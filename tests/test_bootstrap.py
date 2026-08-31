"""Bootstrap installer: exists, --help/--dry-run exit 0, no network camel-ai."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BOOTSTRAP = REPO / "scripts" / "bootstrap.py"


def test_bootstrap_script_exists():
    assert BOOTSTRAP.is_file()
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert "engines" in text
    assert "eve" in text.lower()
    assert "env copy" in text.lower()


def test_help_exits_zero_and_mentions_steps():
    proc = subprocess.run(
        [sys.executable, str(BOOTSTRAP), "--help"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    blob = (proc.stdout + proc.stderr).lower()
    assert "engines" in blob
    assert "eve" in blob
    assert "env" in blob
    assert "dry-run" in blob


def test_dry_run_exits_zero_and_mentions_engines_eve_env():
    proc = subprocess.run(
        [sys.executable, str(BOOTSTRAP), "--dry-run"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    blob = (proc.stdout + proc.stderr).lower()
    assert "engines" in blob
    assert "eve" in blob
    assert "env" in blob
    # Must not have performed a real pip install of camel-ai.
    assert "successfully installed" not in blob
    assert "collecting camel-ai" not in blob
