
"""Offline CLI tests: help, provider table, config redact, setup write to tmp_path."""

from __future__ import annotations

import io
from contextlib import redirect_stdout, redirect_stderr

from eve_miro.cli.main import (
    ALIASES,
    ALIAS_NOTE,
    PROVIDERS,
    USAGE,
    cmd_help,
    main,
    provider_table,
    redact_secret,
    resolve_provider,
)


def test_help_empty_and_help_command():
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main([])
    assert rc == 0
    out = buf.getvalue()
    assert "eve-miro doctor" in out
    assert "eve-miro setup" in out
    assert "eve-miro config show" in out
    assert "eve-miro serve" in out
    assert "eve-miro run" in out
    assert "eve-miro api" in out
    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        rc2 = main(["help"])
    assert rc2 == 0
    assert "doctor" in buf2.getvalue()
    buf3 = io.StringIO()
    with redirect_stdout(buf3):
        rc3 = cmd_help([])
    assert rc3 == 0
    assert "OpenAI-compatible" in USAGE


def test_provider_table():
    table = provider_table()
    for name in ("ollama", "openai", "grok", "deepseek", "openrouter", "azure", "custom"):
        assert name in PROVIDERS
        assert name in table
    assert "anthropic" in table
    assert "gemini" in table
    assert ALIASES["anthropic"] == "openrouter"
    assert ALIASES["gemini"] == "openrouter"
    assert "11434" in table
    assert "openrouter.ai" in table
    assert "OpenAI-compatible" in ALIAS_NOTE
    assert "cookie" in ALIAS_NOTE

    name, updates, note = resolve_provider("ollama")
    assert name == "ollama"
    assert updates["LLM_BASE_URL"] == "http://127.0.0.1:11434/v1"
    assert updates["LLM_API_KEY"] == "local"
    assert updates["LLM_MODEL_NAME"] == "qwen2.5:3b"
    assert updates["MIROFISH_MEMORY"] == "local"
    assert note is None

    name, updates, note = resolve_provider("anthropic", api_key="sk-test-key")
    assert name == "openrouter"
    assert updates["LLM_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert note is not None
    assert "OpenAI-compatible" in note
    assert "cookie" in note

    try:
        resolve_provider("azure", api_key="x")
        raise AssertionError("azure without base-url must fail")
    except ValueError as exc:
        assert "base-url" in str(exc)

    try:
        resolve_provider("openai")
        raise AssertionError("openai without api-key must fail")
    except ValueError as exc:
        assert "api-key" in str(exc)


def test_config_redact():
    assert redact_secret(None) == "empty"
    assert redact_secret("") == "empty"
    assert redact_secret("ab") == "set ****ab"
    assert redact_secret("abcd") == "set ****abcd"
    assert redact_secret("sk-abcdefghij") == "set ****ghij"
    assert "sk-abcdefghij" not in redact_secret("sk-abcdefghij")
    shown = redact_secret("super-secret-value-9999")
    assert shown.startswith("set ****")
    assert len(shown) <= len("set ****") + 4
    assert "super-secret-value-9999" not in shown


def test_setup_write_to_tmp_path(tmp_path):
    env_file = tmp_path / "mirofish.env"
    cfg = tmp_path / "config.toml"
    buf = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = main(
            [
                "setup",
                "--provider",
                "ollama",
                "--env-file",
                str(env_file),
                "--config-file",
                str(cfg),
            ]
        )
    assert rc == 0, buf.getvalue() + err.getvalue()
    text = env_file.read_text(encoding="utf-8")
    assert "LLM_BASE_URL=http://127.0.0.1:11434/v1" in text
    assert "LLM_API_KEY=local" in text
    assert "LLM_MODEL_NAME=qwen2.5:3b" in text
    assert "MIROFISH_MEMORY=local" in text
    assert cfg.is_file()
    assert "ollama" in cfg.read_text(encoding="utf-8")
    # secrets not echoed
    combined = buf.getvalue() + err.getvalue()
    # dummy local key may appear as a word in docs; the cloud-style secret must not
    assert "sk-test" not in combined

    buf2 = io.StringIO()
    with redirect_stdout(buf2), redirect_stderr(err):
        rc2 = main(
            [
                "config",
                "show",
                "--env-file",
                str(env_file),
                "--config-file",
                str(cfg),
            ]
        )
    assert rc2 == 0
    shown = buf2.getvalue()
    assert "provider: ollama" in shown
    assert "set ****ocal" in shown
    assert "LLM_API_KEY: local" not in shown


def test_setup_dry_run_does_not_write(tmp_path):
    env_file = tmp_path / "mirofish.env"
    cfg = tmp_path / "config.toml"
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(
            [
                "setup",
                "--provider",
                "openai",
                "--api-key",
                "sk-not-printed-xyz9",
                "--env-file",
                str(env_file),
                "--config-file",
                str(cfg),
                "--dry-run",
            ]
        )
    assert rc == 0
    assert not env_file.exists()
    assert not cfg.exists()
    out = buf.getvalue()
    assert "sk-not-printed-xyz9" not in out
    assert "LLM_API_KEY" in out


def test_setup_openai_to_tmp(tmp_path):
    env_file = tmp_path / ".env"
    cfg = tmp_path / "config.toml"
    rc = main(
        [
            "setup",
            "--provider",
            "grok",
            "--api-key",
            "xai-secret-key-4242",
            "--env-file",
            str(env_file),
            "--config-file",
            str(cfg),
        ]
    )
    assert rc == 0
    text = env_file.read_text(encoding="utf-8")
    assert "LLM_BASE_URL=https://api.x.ai/v1" in text
    assert "LLM_MODEL_NAME=grok-2-latest" in text
    assert "LLM_API_KEY=xai-secret-key-4242" in text
    assert "provider = \"grok\"" in cfg.read_text(encoding="utf-8")


def test_config_set_from_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setenv("EVE_MIRO_VALUE", "hidden-value-7788")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["config", "set", "LLM_API_KEY", "--env-file", str(env_file)])
    assert rc == 0
    assert "hidden-value-7788" not in buf.getvalue()
    assert env_file.read_text(encoding="utf-8").strip() == "LLM_API_KEY=hidden-value-7788"


def test_unknown_command():
    buf = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = main(["not-a-command"])
    assert rc == 2

def test_install_scripts_at_repo_root():
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    sh = repo / "install.sh"
    ps1 = repo / "install.ps1"
    assert sh.is_file()
    assert ps1.is_file()
    sh_text = sh.read_text(encoding="utf-8")
    ps_text = ps1.read_text(encoding="utf-8")
    for blob in (sh_text, ps_text):
        assert "--help" in blob or "-Help" in blob
        assert "--dir" in blob or "-Dir" in blob
        assert "--skip-setup" in blob or "-SkipSetup" in blob
        assert "PYTHONPATH" in blob
    assert "fernandogarzaaa/EVE---MIRO" in sh_text
    assert "eve-miro doctor" in sh_text
    assert "eve-miro serve" in sh_text
    assert "eve-miro run" in sh_text
