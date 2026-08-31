"""In-tree MiroFish / EVE copies are first-party source of truth."""

from __future__ import annotations

from pathlib import Path

from eve_miro.core.experience.eve_adapter import EVEExperienceEngine, in_tree_available as eve_in_tree
from eve_miro.core.simulation.mirofish_adapter import MiroFishEngine, in_tree_available as mirofish_in_tree
from eve_miro.paths import EVE_ROOT, MIROFISH_ROOT, REPO_ROOT, eve_root, mirofish_root


def test_origin_files_exist():
    assert (MIROFISH_ROOT / "ORIGIN.txt").is_file()
    assert (EVE_ROOT / "ORIGIN.txt").is_file()


def test_engine_trees_present():
    assert (MIROFISH_ROOT / "backend" / "app").is_dir()
    assert (EVE_ROOT / "src" / "index.ts").is_file()


def test_no_nested_git():
    assert not (MIROFISH_ROOT / ".git").exists()
    assert not (EVE_ROOT / ".git").exists()


def test_paths_resolve_to_repo():
    assert REPO_ROOT.name == "eve-miro" or (REPO_ROOT / "pyproject.toml").is_file()
    assert MIROFISH_ROOT == REPO_ROOT / "mirofish"
    assert EVE_ROOT == REPO_ROOT / "eve"
    assert mirofish_root().resolve() == MIROFISH_ROOT.resolve()
    assert eve_root().resolve() == EVE_ROOT.resolve()
    assert MIROFISH_ROOT.is_dir()
    assert EVE_ROOT.is_dir()


def test_adapters_report_in_tree_available():
    assert mirofish_in_tree() is True
    assert eve_in_tree() is True
    assert MiroFishEngine().using_remote is False
    assert EVEExperienceEngine().using_remote is False


def test_pytest_does_not_need_network_or_llm(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("ZEP_API_KEY", raising=False)
    monkeypatch.delenv("MIROFISH_URL", raising=False)
    monkeypatch.delenv("EVE_URL", raising=False)
    monkeypatch.delenv("EVE_MIRO_ENGINES", raising=False)
    assert mirofish_in_tree()
    assert eve_in_tree()
