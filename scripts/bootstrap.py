#!/usr/bin/env python3
"""Universal first-clone bootstrap for EVE-MIRO.

Stdlib-first. Python 3.12+.

Installs, in one command:
  * repo-root .venv on Python 3.12+ (fabric + tests via pip install -e ".[dev]")
  * mirofish/.venv on Python 3.11 when available (engines / camel-oasis)
  * pip install -r mirofish/backend/requirements.txt into the 3.11 venv
  * EVE CLI build (eve/bin/eve.js / eve/dist/cli/main.js)
  * env copy: .env.example -> .env and mirofish/.env.example -> mirofish/.env
    only when the destination is missing (never overwrite, never invent API keys)

--dry-run prints these steps and does not install.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

MIN_PY = (3, 12)
MIROFISH_WARN_PY = (3, 13)

DEBIAN_HINT = "Debian: build-essential + nodejs"
WINDOWS_HINT = "Windows: MSVC Build Tools + Node LTS"
MAC_HINT = "macOS: Xcode CLT + Homebrew node"

TOOL_BINS = ('node', 'npm')
COMPILER_BINS = ('g++', 'clang++', 'cl')


def repo_root() -> Path:
    """Repository root is the parent of scripts/."""
    return Path(__file__).resolve().parent.parent


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> None:
    print("error: " + msg, file=sys.stderr, flush=True)
    raise SystemExit(code)


def platform_hint() -> str:
    if sys.platform == "win32":
        return WINDOWS_HINT
    if sys.platform == "darwin":
        return MAC_HINT + "\n" + DEBIAN_HINT
    return DEBIAN_HINT + "\n" + WINDOWS_HINT


def find_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if sys.platform == "win32":
        return shutil.which(name + ".cmd") or shutil.which(name + ".exe")
    return None


def venv_python_path(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"



def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    log("+ " + " ".join(cmd))
    try:
        subprocess.run(cmd, cwd=cwd, check=True, env=env)
    except FileNotFoundError:
        die("command not found: " + cmd[0] + "\n" + platform_hint())
    except subprocess.CalledProcessError as exc:
        die("command failed (exit %s): %s" % (exc.returncode, " ".join(cmd)))


def capture(cmd: list[str], *, cwd: Path | None = None) -> str | None:
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, check=True, capture_output=True, text=True, timeout=20
        )
    except (FileNotFoundError, subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip()


def find_python_minor(minor: int) -> Path | None:
    """Locate python3.<minor> on PATH or the Windows py launcher."""
    names = ("python3.%s" % minor, "python3%s" % minor)
    for name in names:
        exe = find_tool(name)
        if exe:
            return Path(exe)
    if sys.platform == "win32":
        launcher = find_tool("py")
        if launcher:
            out = capture([launcher, "-3.%s" % minor, "-c", "import sys; print(sys.executable)"])
            if out:
                found = Path(out)
                if found.is_file():
                    return found
    if sys.version_info[:2] == (3, minor):
        return Path(sys.executable)
    return None


def find_python312() -> Path | None:
    """Locate a 3.12 interpreter when the current one is 3.13+."""
    return find_python_minor(12)


def find_python311() -> Path | None:
    """Locate a 3.11 interpreter for OASIS (camel-oasis needs 3.10-3.11)."""
    return find_python_minor(11)


def pick_create_python() -> Path:
    """Interpreter used to create .venv. Prefer 3.12 on 3.13+ hosts."""
    current = Path(sys.executable)
    ver = sys.version_info[:2]
    if ver < MIN_PY:
        die(
            "Python %s.%s is too old (need >=3.12).\n%s"
            % (ver[0], ver[1], platform_hint())
        )
    if ver >= MIROFISH_WARN_PY:
        log(
            "warning: Python %s.%s detected. MiroFish historically wants <3.13 "
            "(camel-oasis / camel-ai). Prefer one venv at repo root on 3.12."
            % (ver[0], ver[1])
        )
        found = find_python312()
        if found:
            log("using %s to create .venv (still one venv at repo root)" % found)
            return found
        log(
            "warning: python3.12 not on PATH; continuing with this interpreter. "
            "camel-oasis install is known-fragile on 3.13. Failure is loud. "
            "Install Python 3.12 for fabric; OASIS still needs 3.11 at mirofish/.venv."
        )
    return current



def preflight(root: Path, *, fatal: bool) -> None:
    problems: list[str] = []
    ver = sys.version_info
    if (ver.major, ver.minor) < MIN_PY:
        problems.append(
            "Python %s.%s is too old (need >=3.12)." % (ver.major, ver.minor)
        )
    elif (ver.major, ver.minor) >= MIROFISH_WARN_PY:
        log(
            "preflight: Python %s.%s (warn: MiroFish wants <3.13)"
            % (ver.major, ver.minor)
        )
    else:
        log("preflight: Python %s.%s.%s" % (ver.major, ver.minor, ver.micro))

    for name in TOOL_BINS:
        path = find_tool(name)
        if path:
            extra = capture([path, "-v"]) or ""
            log("preflight: %s %s (%s)" % (name, extra, path))
        else:
            problems.append("%s not found on PATH." % name)

    cxx = None
    for name in COMPILER_BINS:
        cxx = find_tool(name)
        if cxx:
            break
    if cxx:
        log("preflight: C/C++ compiler (%s)" % cxx)
    else:
        problems.append(
            "C/C++ compiler not found (need a C++ compiler). "
            "camel-oasis / camel-ai may need a compiler."
        )

    needed = [
        root / "pyproject.toml",
        root / "mirofish" / "backend" / "requirements.txt",
        root / "eve" / "package.json",
        root / ".env.example",
        root / "mirofish" / ".env.example",
    ]
    for path in needed:
        if not path.is_file():
            problems.append("missing %s" % path.relative_to(root))

    if not problems:
        return
    msg = "preflight failed:\n  - " + "\n  - ".join(problems) + "\n" + platform_hint()
    if fatal:
        die(msg)
    log("warning: " + msg)



def ensure_venv(root: Path, create_py: Path, *, dry_run: bool) -> Path:
    venv_dir = root / ".venv"
    vpy = venv_python_path(venv_dir)
    if dry_run:
        log("[dry-run] create %s with %s if missing" % (venv_dir, create_py))
        return vpy
    if vpy.is_file():
        log("using existing venv interpreter %s" % vpy)
        return vpy
    log("creating venv %s" % venv_dir)
    try:
        subprocess.run([str(create_py), "-m", "venv", str(venv_dir)], check=True)
    except FileNotFoundError:
        die("cannot run %s to create venv\n%s" % (create_py, platform_hint()))
    except subprocess.CalledProcessError:
        die(
            "failed to create .venv. Debian: python3-venv + python3-pip. "
            + platform_hint()
        )
    if not vpy.is_file():
        die("venv created but interpreter missing: %s" % vpy)
    return vpy


def run_ok(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> bool:
    log("+ " + " ".join(cmd))
    try:
        subprocess.run(cmd, cwd=cwd, check=True, env=env)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def pip_install(root: Path, vpy: Path, *, dry_run: bool) -> None:
    req = root / "mirofish" / "backend" / "requirements.txt"
    extra = ".[dev]"
    if dry_run:
        log("[dry-run] %s -m pip install -U pip setuptools wheel" % vpy)
        log("[dry-run] %s -m pip install -e %s  (fabric + tests)" % (vpy, extra))
        log("[dry-run] engines extra / OASIS requirements go in mirofish/.venv on Python 3.11")
        log("[dry-run] %s -m pip install -r %s  (into OASIS 3.11 venv when present)" % (vpy, req))
        return
    env = os.environ.copy()
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    run([str(vpy), "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"], cwd=root, env=env)
    run([str(vpy), "-m", "pip", "install", "-e", extra], cwd=root, env=env)
    if not run_ok([str(vpy), "-m", "pip", "install", "-e", ".[engines]"], cwd=root, env=env):
        log("warning: engines extra failed in fabric venv (camel-oasis needs Python 3.11).")
        log("  OASIS will be installed into mirofish/.venv when python3.11 exists.")



def ensure_oasis_venv(root: Path, *, dry_run: bool) -> None:
    req = root / "mirofish" / "backend" / "requirements.txt"
    oasis_venv = root / "mirofish" / ".venv"
    py311 = find_python311()
    if dry_run:
        log("[dry-run] engines / OASIS: if Python 3.11 exists, pip install -r %s into %s" % (req, oasis_venv))
        if not py311:
            log("[dry-run] warning: python3.11 not on PATH; camel-oasis needs 3.10-3.11")
        return
    if not py311:
        log("warning: Python 3.11 not found. OASIS (camel-oasis==0.2.5) needs 3.10-3.11.")
        log("  Create mirofish/.venv with 3.11 then: pip install -r mirofish/backend/requirements.txt")
        return
    vpy = venv_python_path(oasis_venv)
    if not vpy.is_file():
        log("creating OASIS venv %s with %s" % (oasis_venv, py311))
        try:
            subprocess.run([str(py311), "-m", "venv", str(oasis_venv)], check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            die("failed to create mirofish/.venv with %s" % py311)
    if not vpy.is_file():
        die("OASIS venv created but interpreter missing: %s" % vpy)
    env = os.environ.copy()
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    run([str(vpy), "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"], cwd=root, env=env)
    run([str(vpy), "-m", "pip", "install", "-r", str(req)], cwd=root, env=env)
    log("OASIS venv ready: %s" % vpy)


def build_eve(root: Path, *, dry_run: bool) -> None:
    eve = root / "eve"
    bin_js = eve / "bin" / "eve.js"
    dist_js = eve / "dist" / "cli" / "main.js"

    pkg_mgr = find_tool(TOOL_BINS[1])
    lock = eve / "package-lock.json"
    step = "ci" if lock.is_file() else "install"
    if dry_run:
        log("[dry-run] in eve/: %s %s then build" % (TOOL_BINS[1], step))
        log("[dry-run] expect eve/bin/eve.js or eve/dist/cli/main.js")
        return
    if not eve.is_dir():
        die("eve/ tree missing")
    if not pkg_mgr:
        die(TOOL_BINS[1] + " not found; cannot build EVE CLI.\n" + platform_hint())

    run([pkg_mgr, step], cwd=eve)
    run([pkg_mgr, "run", "build"], cwd=eve)
    if not bin_js.is_file() and not dist_js.is_file():
        die("EVE build did not produce eve/bin/eve.js or eve/dist/cli/main.js")
    log("EVE CLI: %s" % (bin_js if bin_js.is_file() else dist_js))


def copy_env_if_missing(src: Path, dest: Path, *, dry_run: bool) -> None:
    if dest.exists():
        log("keep existing %s (env copy skipped; never overwrite)" % dest)
        return
    if dry_run:
        log("[dry-run] env copy %s -> %s (only if missing; never overwrite; never invent API keys)" % (src, dest))
        return
    if not src.is_file():
        die("missing env template %s" % src)
    shutil.copyfile(src, dest)
    log("env copy %s -> %s" % (src.name, dest))



def recap(root: Path) -> None:
    if sys.platform == "win32":
        activate = ".venv\\Scripts\\activate"
    else:
        activate = "source .venv/bin/activate"
    gguf = root / "models" / "qwen2.5-0.5b-instruct-q4_k_m.gguf"
    log("")
    log("=== EVE-MIRO bootstrap complete ===")
    log("Activate: %s" % activate)
    log("Python split: fabric .venv is 3.12+; OASIS is mirofish/.venv on 3.11.")
    log("CLI: eve-miro / eve-miro setup / eve-miro doctor / eve-miro serve / eve-miro run")
    log("pytest (offline stubs via tests/conftest.py; no LLM / server / node build):")
    log("  python -m pytest -q")
    log("Boot MiroFish Flask on 5001:")
    log("  eve-miro serve")
    log("  # or mirofish/.venv python mirofish/backend/run.py")
    log("Boot EVE-MIRO API on 8000:")
    log("  eve-miro api")
    log("  # or FIXTURES=1 EVE_MIRO_ENGINES=in-tree python -m uvicorn eve_miro.api.main:app --port 8000")
    log("Fail-closed: POST /experiments/run returns 503 without LLM keys or a")
    log("  running MiroFish server / built EVE CLI (never a silent stub).")
    log("Pytest stays stub via tests/conftest.py (EVE_MIRO_ENGINES=stub).")
    log("Local GGUF path (see README): %s" % gguf.as_posix())
    log("  LLM_API_KEY=local  LLM_BASE_URL=http://127.0.0.1:8088/v1")
    log("  LLM_MODEL_NAME=qwen2.5-0.5b-instruct")
    log("  python scripts/local_llm_server.py")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Universal EVE-MIRO install: pip extras (dev + engines), "
            "MiroFish backend requirements, EVE CLI build, env copy "
            "(.env.example -> .env if missing)."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print engines / eve / env copy steps; do not install.",
    )
    return parser.parse_args(argv)



def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = repo_root()
    dry = bool(args.dry_run)
    if dry:
        log("dry-run: print steps, do not install")
    log("repo root: %s" % root)

    if sys.version_info[:2] < MIN_PY:
        die(
            "Python %s.%s is too old (need >=3.12).\n%s"
            % (sys.version_info.major, sys.version_info.minor, platform_hint())
        )

    preflight(root, fatal=not dry)
    create_py = pick_create_python()
    vpy = ensure_venv(root, create_py, dry_run=dry)
    pip_install(root, vpy, dry_run=dry)
    ensure_oasis_venv(root, dry_run=dry)
    build_eve(root, dry_run=dry)
    copy_env_if_missing(root / ".env.example", root / ".env", dry_run=dry)
    copy_env_if_missing(
        root / "mirofish" / ".env.example",
        root / "mirofish" / ".env",
        dry_run=dry,
    )
    recap(root)
    if dry:
        log("dry-run finished (nothing installed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
