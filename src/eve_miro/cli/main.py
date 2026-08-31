"""EVE-MIRO CLI: doctor, setup, config, serve, run, api.

Console script: ``eve-miro = eve_miro.cli.main:main``.
Uvicorn stays available as ``eve-miro api``.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from eve_miro.paths import REPO_ROOT

PROG = "eve-miro"
CONFIG_DIR = Path.home() / ".eve-miro"
DEFAULT_CONFIG = CONFIG_DIR / "config.toml"
MIROFISH_ENV = REPO_ROOT / "mirofish" / ".env"
SECRET_KEYS = {
    "LLM_API_KEY",
    "API_KEY",
    "ZEP_API_KEY",
    "LLM_BOOST_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
}

# OpenAI-compatible HTTP only. MiroFish uses the OpenAI SDK.
# Anthropic/Gemini/Claude websites are not scraped; use OpenRouter or a gateway.
PROVIDERS: dict[str, dict[str, Any]] = {
    "ollama": {
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key": "local",
        "model": "qwen2.5:3b",
        "requires_api_key": False,
        "requires_base_url": False,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key": None,
        "model": "gpt-4o-mini",
        "requires_api_key": True,
        "requires_base_url": False,
    },
    "grok": {
        "base_url": "https://api.x.ai/v1",
        "api_key": None,
        "model": "grok-2-latest",
        "requires_api_key": True,
        "requires_base_url": False,
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": None,
        "model": "deepseek-chat",
        "requires_api_key": True,
        "requires_base_url": False,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": None,
        "model": "openai/gpt-4o-mini",
        "requires_api_key": True,
        "requires_base_url": False,
    },
    "azure": {
        "base_url": None,
        "api_key": None,
        "model": None,
        "requires_api_key": True,
        "requires_base_url": True,
    },
    "custom": {
        "base_url": None,
        "api_key": None,
        "model": None,
        "requires_api_key": True,
        "requires_base_url": True,
    },
}

ALIASES = {
    "anthropic": "openrouter",
    "gemini": "openrouter",
}

ALIAS_NOTE = (
    "MiroFish speaks OpenAI-compatible HTTP; use OpenRouter or a gateway, "
    "not cookie login."
)

USAGE = """\
EVE-MIRO — reality-grounded experiential simulation

Usage:
  eve-miro                 show this help
  eve-miro help            show this help
  eve-miro doctor          check python 3.11 / OASIS, node, eve.js (flask/ollama optional)
  eve-miro setup           write LLM keys (TTY prompts, or --provider/--api-key/...)
  eve-miro config show     show config with secrets redacted
  eve-miro config set KEY  set a key (value from EVE_MIRO_VALUE or getpass)
  eve-miro serve           start MiroFish Flask (:5001)
  eve-miro run             live tiny closed loop (EVE_MIRO_ENGINES=in-tree, fail closed)
  eve-miro api             uvicorn eve_miro.api.main:app :8000

Setup flags (non-interactive):
  --provider NAME    ollama|openai|grok|deepseek|openrouter|azure|custom
                     (anthropic and gemini alias to openrouter)
  --api-key KEY
  --base-url URL     required for azure/custom
  --model NAME

Providers (OpenAI-compatible HTTP only):
  ollama       http://127.0.0.1:11434/v1   key=local   qwen2.5:3b
  openai       https://api.openai.com/v1               gpt-4o-mini
  grok         https://api.x.ai/v1                     grok-2-latest
  deepseek     https://api.deepseek.com/v1             deepseek-chat
  openrouter   https://openrouter.ai/api/v1            Anthropic/Gemini/Claude via paid key
  azure        --base-url required
  custom       --base-url required

Python split: fabric is 3.12+ (.venv). OASIS is 3.11 (mirofish/.venv).
"""



def is_tty() -> bool:
    return bool(getattr(sys.stdin, "isatty", lambda: False)() and getattr(sys.stdout, "isatty", lambda: False)())


def venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def fabric_python() -> Path:
    vpy = venv_python(REPO_ROOT / ".venv")
    if vpy.is_file():
        return vpy
    return Path(sys.executable)


def oasis_python() -> Path | None:
    vpy = venv_python(REPO_ROOT / "mirofish" / ".venv")
    if vpy.is_file():
        return vpy
    found = shutil.which("python3.11") or shutil.which("python311")
    return Path(found) if found else None


def provider_table() -> str:
    lines = [
        "provider     base_url                         model",
        "------------ -------------------------------- --------------------",
    ]
    for name, spec in PROVIDERS.items():
        base = spec["base_url"] or "--base-url required"
        model = spec["model"] or "(user)"
        lines.append(f"{name:<12} {base:<32} {model}")
    lines.append("anthropic    alias → openrouter             (OpenAI-compatible gateway)")
    lines.append("gemini       alias → openrouter             (OpenAI-compatible gateway)")
    lines.append(ALIAS_NOTE)
    return "\n".join(lines)


def resolve_provider(
    name: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> tuple[str, dict[str, str], str | None]:
    """Return (canonical_name, env_updates, optional_note)."""
    raw = (name or "").strip().lower()
    if not raw:
        raise ValueError("provider name is required")
    note: str | None = None
    if raw in ALIASES:
        note = f"{raw} maps to openrouter. {ALIAS_NOTE}"
        raw = ALIASES[raw]
    if raw not in PROVIDERS:
        known = ", ".join(list(PROVIDERS) + list(ALIASES))
        raise ValueError(f"unknown provider {name!r}. choose from {known}")
    spec = PROVIDERS[raw]
    resolved_base = (base_url or spec["base_url"] or "").strip()
    resolved_model = (model or spec["model"] or "").strip()
    resolved_key = api_key if api_key is not None else spec["api_key"]
    if spec["requires_base_url"] and not resolved_base:
        raise ValueError(f"provider {raw} requires --base-url")
    if spec["requires_api_key"] and not resolved_key:
        raise ValueError(f"provider {raw} requires --api-key (will not invent a key)")
    if not resolved_base:
        raise ValueError(f"provider {raw} is missing a base URL")
    if not resolved_model:
        raise ValueError(f"provider {raw} requires --model")
    if not resolved_key:
        raise ValueError(f"provider {raw} requires an API key")
    updates = {
        "LLM_API_KEY": str(resolved_key),
        "LLM_BASE_URL": resolved_base,
        "LLM_MODEL_NAME": resolved_model,
        "MIROFISH_MEMORY": "local",
    }
    return raw, updates, note


def redact_secret(value: str | None) -> str:
    """Show set/empty plus at most the last 4 characters. Never the full secret."""
    if value is None:
        return "empty"
    text = str(value)
    if text == "":
        return "empty"
    tail = text[-4:] if len(text) >= 1 else ""
    if len(tail) > 4:
        tail = tail[-4:]
    return f"set ****{tail}"


def is_secret_key(key: str) -> bool:
    upper = key.upper()
    if upper in SECRET_KEYS:
        return True
    return any(token in upper for token in ("API_KEY", "SECRET", "TOKEN", "PASSWORD"))


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key.strip()] = value
    return out


def upsert_env_file(path: Path, updates: dict[str, str]) -> None:
    """Write keys without echoing values. Never overwrite unrelated keys."""
    lines: list[str] = []
    seen: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in updates:
                    lines.append(f"{key}={updates[key]}")
                    seen.add(key)
                    continue
            lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def write_config_toml(path: Path, provider: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = f'provider = "{provider}"\n'
    path.write_text(body, encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def read_config_toml(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 400
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def cmd_help(_args: list[str] | None = None) -> int:
    print(USAGE)
    return 0



def cmd_doctor(_args=None) -> int:
    ok = True
    py311 = oasis_python()
    if py311 is None:
        print("FAIL  python 3.11 not found (OASIS / camel-oasis needs 3.10-3.11 at mirofish/.venv)")
        ok = False
    else:
        code = "import oasis, sys; print(sys.version.split()[0])"
        proc = subprocess.run([str(py311), "-c", code], capture_output=True, text=True, timeout=30, check=False)
        if proc.returncode == 0:
            print("ok    oasis import (%s %s)" % (py311, proc.stdout.strip()))
        else:
            err = (proc.stderr or proc.stdout or "import failed").strip().splitlines()
            tail = err[-1] if err else "import failed"
            print("FAIL  oasis import via %s: %s" % (py311, tail))
            ok = False
    node_bin = shutil.which("node")
    npm_bin = shutil.which("npm")
    if node_bin:
        print("ok    node (%s)" % node_bin)
    else:
        print("FAIL  node not on PATH (see nodejs.org)")
        ok = False
    if npm_bin:
        print("ok    npm (%s)" % npm_bin)
    else:
        print("FAIL  npm not on PATH")
        ok = False
    eve_js = REPO_ROOT / "eve" / "bin" / "eve.js"
    eve_dist = REPO_ROOT / "eve" / "dist" / "cli" / "main.js"
    if eve_js.is_file():
        print("ok    eve.js %s" % eve_js)
    elif eve_dist.is_file():
        print("ok    eve dist %s" % eve_dist)
    else:
        print("FAIL  eve/bin/eve.js missing (run the installer or npm run build in eve/)")
        ok = False
    flask_url = "http://127.0.0.1:5001/health"
    if _http_ok(flask_url):
        print("ok    flask health %s" % flask_url)
    else:
        print("skip  flask health (optional; start with: eve-miro serve)")
    ollama_url = "http://127.0.0.1:11434/api/tags"
    if _http_ok(ollama_url):
        print("ok    ollama http://127.0.0.1:11434")
    else:
        print("skip  ollama (optional)")
    return 0 if ok else 1



def _prompt(msg: str, default: str = "") -> str:
    suffix = " [%s]" % default if default else ""
    raw = input("%s%s: " % (msg, suffix)).strip()
    return raw or default


def cmd_setup(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="eve-miro setup", add_help=True)
    parser.add_argument("--provider", help="ollama|openai|grok|deepseek|openrouter|azure|custom")
    parser.add_argument("--api-key", dest="api_key", default=None, help="LLM API key (never echoed)")
    parser.add_argument("--base-url", dest="base_url", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--env-file", dest="env_file", default=None)
    parser.add_argument("--config-file", dest="config_file", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    provider_name = args.provider
    api_key = args.api_key
    base_url = args.base_url
    model = args.model
    tty = is_tty()

    if not provider_name:
        if not tty:
            provider_name = "ollama"
            print("non-interactive: defaulting --provider ollama (local, key=local).")
            print("pass --provider/--api-key/--base-url/--model to override. never invents cloud keys.")
        else:
            print(provider_table())
            print()
            provider_name = _prompt("Provider", "ollama")

    canonical = (provider_name or "").strip().lower()
    mapped = ALIASES.get(canonical, canonical)
    spec = PROVIDERS.get(mapped)

    if spec and spec["requires_api_key"] and not api_key:
        if tty:
            api_key = getpass.getpass("API key (input hidden): ")
        else:
            print("error: provider requires --api-key (refusing to invent a key)", file=sys.stderr)
            return 1
    if spec and spec["requires_base_url"] and not base_url:
        if tty:
            base_url = _prompt("Base URL")
        else:
            print("error: provider requires --base-url", file=sys.stderr)
            return 1
    if spec and not (model or spec.get("model")):
        if tty:
            model = _prompt("Model")
        else:
            print("error: provider requires --model", file=sys.stderr)
            return 1

    try:
        canonical, updates, note = resolve_provider(
            provider_name, api_key=api_key, base_url=base_url, model=model
        )
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    if note:
        print(note)

    env_file = Path(args.env_file).expanduser() if args.env_file else MIROFISH_ENV
    config_file = Path(args.config_file).expanduser() if args.config_file else DEFAULT_CONFIG

    if args.dry_run:
        print("dry-run would write %s keys: %s" % (env_file, ", ".join(updates)))
        print("dry-run would write %s provider=%s" % (config_file, canonical))
        for key in updates:
            shown = redact_secret(updates[key]) if is_secret_key(key) else updates[key]
            print("  %s=%s" % (key, shown))
        return 0

    upsert_env_file(env_file, updates)
    write_config_toml(config_file, canonical)
    print("wrote %s (LLM_API_KEY LLM_BASE_URL LLM_MODEL_NAME MIROFISH_MEMORY=local)" % env_file)
    print("wrote %s provider=%s" % (config_file, canonical))
    return 0


def cmd_config(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print("Usage: eve-miro config show")
        print("       eve-miro config set KEY")
        return 0
    action = argv[0]
    rest = argv[1:]
    if action == "show":
        return cmd_config_show(rest)
    if action == "set":
        return cmd_config_set(rest)
    print("error: unknown config action %r" % action, file=sys.stderr)
    return 2


def cmd_config_show(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="eve-miro config show")
    parser.add_argument("--env-file", dest="env_file", default=None)
    parser.add_argument("--config-file", dest="config_file", default=None)
    args = parser.parse_args(argv)
    env_file = Path(args.env_file).expanduser() if args.env_file else MIROFISH_ENV
    config_file = Path(args.config_file).expanduser() if args.config_file else DEFAULT_CONFIG

    cfg = read_config_toml(config_file)
    provider = cfg.get("provider", "")
    print("config: %s" % config_file)
    print("  provider: %s" % (provider or "empty"))
    print("env: %s" % env_file)
    if not env_file.is_file():
        print("  (missing)")
        return 0
    data = read_env_file(env_file)
    keys = ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL_NAME", "MIROFISH_MEMORY"]
    extra = [k for k in data if k not in keys]
    for key in keys + extra:
        if key not in data:
            print("  %s: empty" % key)
            continue
        value = data[key]
        shown = redact_secret(value) if is_secret_key(key) else (value if value else "empty")
        print("  %s: %s" % (key, shown))
    return 0


def cmd_config_set(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="eve-miro config set")
    parser.add_argument("key")
    parser.add_argument("--env-file", dest="env_file", default=None)
    parser.add_argument("--config-file", dest="config_file", default=None)
    args = parser.parse_args(argv)
    key = args.key.strip()
    if not key:
        print("error: KEY is required", file=sys.stderr)
        return 1
    value = os.environ.get("EVE_MIRO_VALUE")
    if value is None:
        if not is_tty():
            print("error: set EVE_MIRO_VALUE or run on a TTY (value is never printed)", file=sys.stderr)
            return 1
        value = getpass.getpass("%s (input hidden): " % key)
    if key.lower() == "provider":
        config_file = Path(args.config_file).expanduser() if args.config_file else DEFAULT_CONFIG
        write_config_toml(config_file, value.strip())
        print("updated %s" % key)
        return 0
    env_file = Path(args.env_file).expanduser() if args.env_file else MIROFISH_ENV
    upsert_env_file(env_file, {key: value})
    print("updated %s" % key)
    return 0


def cmd_serve(_args=None) -> int:
    script = REPO_ROOT / "mirofish" / "backend" / "run.py"
    if not script.is_file():
        print("error: missing %s" % script, file=sys.stderr)
        return 1
    for candidate in (REPO_ROOT / "mirofish" / ".venv", REPO_ROOT / ".venv"):
        py = venv_python(candidate)
        if py.is_file():
            print("starting MiroFish with %s (%s)" % (py, script))
            proc = subprocess.run([str(py), str(script)], check=False)
            return int(proc.returncode)
    print("error: no mirofish/.venv or .venv python found", file=sys.stderr)
    return 1


def cmd_run(_args=None) -> int:
    script = REPO_ROOT / "scripts" / "run_live_tiny_loop.py"
    if not script.is_file():
        print("error: missing %s" % script, file=sys.stderr)
        return 1
    env = os.environ.copy()
    env["EVE_MIRO_ENGINES"] = "in-tree"
    env.setdefault("MIROFISH_URL", "http://127.0.0.1:5001")
    env.setdefault("MIROFISH_MEMORY", "local")
    print("running live tiny loop (EVE_MIRO_ENGINES=in-tree, fail closed)")
    proc = subprocess.run([str(fabric_python()), str(script)], env=env, check=False)
    return int(proc.returncode)


def cmd_api(argv: list[str]) -> int:
    try:
        import uvicorn
    except ImportError:
        print("error: uvicorn is not installed (pip install -e .)", file=sys.stderr)
        return 1
    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "8000"))
    i = 0
    while i < len(argv):
        if argv[i] == "--host" and i + 1 < len(argv):
            host = argv[i + 1]
            i += 2
            continue
        if argv[i] == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
            i += 2
            continue
        i += 1
    print("uvicorn eve_miro.api.main:app --host %s --port %s" % (host, port))
    uvicorn.run("eve_miro.api.main:app", host=host, port=port)
    return 0


COMMANDS = {
    "help": cmd_help,
    "doctor": cmd_doctor,
    "setup": cmd_setup,
    "config": cmd_config,
    "serve": cmd_serve,
    "run": cmd_run,
    "api": cmd_api,
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"help", "-h", "--help"}:
        return cmd_help(args[1:] if args else [])
    cmd = args[0]
    rest = args[1:]
    handler = COMMANDS.get(cmd)
    if handler is None:
        print(USAGE, file=sys.stderr)
        print("error: unknown command %r" % cmd, file=sys.stderr)
        return 2
    try:
        return int(handler(rest))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
