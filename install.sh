#!/usr/bin/env bash
# EVE-MIRO one-liner installer (Linux / macOS).
# curl -fsSL https://raw.githubusercontent.com/fernandogarzaaa/EVE---MIRO/main/install.sh | bash
set -euo pipefail

if [ -n "${PYTHONPATH:-}" ]; then
  echo "Ignoring inherited PYTHONPATH during install to avoid module shadowing"
  unset PYTHONPATH
fi
if [ -n "${PYTHONHOME:-}" ]; then
  echo "Ignoring inherited PYTHONHOME during install"
  unset PYTHONHOME
fi

REPO_URL="https://github.com/fernandogarzaaa/EVE---MIRO.git"
BRANCH="main"
EVE_MIRO_HOME="${EVE_MIRO_HOME:-$HOME/.eve-miro}"
INSTALL_DIR=""
SKIP_SETUP=false

if [ -t 0 ]; then
  IS_INTERACTIVE=true
else
  IS_INTERACTIVE=false
fi

usage() {
  cat <<EOF
EVE-MIRO installer

Usage: install.sh [OPTIONS]

Options:
  --dir PATH        Clone/update destination (default: ~/.eve-miro/src)
  --skip-setup      Do not run eve-miro setup
  -h, --help        Show this help

One-liners:
  curl -fsSL https://raw.githubusercontent.com/fernandogarzaaa/EVE---MIRO/main/install.sh | bash
  iex (irm https://raw.githubusercontent.com/fernandogarzaaa/EVE---MIRO/main/install.ps1)
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dir)
      INSTALL_DIR="$2"
      shift 2
      ;;
    --skip-setup)
      SKIP_SETUP=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [ -z "$INSTALL_DIR" ]; then
  INSTALL_DIR="${EVE_MIRO_HOME}/src"
fi

log() { printf "-> %s\n" "$1"; }
ok() { printf "ok %s\n" "$1"; }
warn() { printf "warning: %s\n" "$1" >&2; }
die() { printf "error: %s\n" "$1" >&2; exit 1; }

case "$(uname -s)" in
  CYGWIN*|MINGW*|MSYS*)
    die "Windows detected. Use: iex (irm https://raw.githubusercontent.com/fernandogarzaaa/EVE---MIRO/main/install.ps1)"
    ;;
esac

have() { command -v "$1" >/dev/null 2>&1; }

sudo_if() {
  if [ "$(id -u 2>/dev/null || echo 1000)" -eq 0 ]; then
    "$@"
  elif have sudo; then
    sudo "$@"
  else
    return 1
  fi
}

install_git() {
  if have git && git --version >/dev/null 2>&1; then
    ok "git $(git --version | awk "{print \$3}")"
    return 0
  fi
  log "git not found; trying package manager"
  OS="$(uname -s)"
  if [ "$OS" = "Darwin" ] && have brew; then
    brew install git >/dev/null 2>&1 || true
  elif have apt-get; then
    sudo_if env DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1 || true
    sudo_if env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git >/dev/null 2>&1 || true
  elif have dnf; then
    sudo_if dnf install -y git >/dev/null 2>&1 || true
  elif have pacman; then
    sudo_if pacman -S --noconfirm git >/dev/null 2>&1 || true
  fi
  if have git && git --version >/dev/null 2>&1; then
    ok "git installed"
    return 0
  fi
  echo "Install git, then re-run:"
  echo "  Debian/Ubuntu: sudo apt-get install git"
  echo "  macOS: brew install git   or  xcode-select --install"
  echo "  Fedora: sudo dnf install git"
  die "git is required"
}

py_ver() {
  "$1" -c "import sys; print(\"%s.%s\" % (sys.version_info[0], sys.version_info[1]))" 2>/dev/null || true
}

find_py() {
  local want="$1"
  local c
  for c in python${want} python3 python; do
    if have "$c"; then
      local v
      v="$(py_ver "$(command -v "$c")")"
      if [ "$v" = "$want" ]; then
        command -v "$c"
        return 0
      fi
    fi
  done
  return 1
}

find_py_ge() {
  local min_major=3 min_minor=12
  local c v major minor
  for c in python3.13 python3.12 python3 python; do
    if have "$c"; then
      v="$(py_ver "$(command -v "$c")")"
      major="${v%%.*}"
      minor="${v#*.}"
      if [ -n "$major" ] && [ -n "$minor" ] && [ "$major" -gt "$min_major" ] 2>/dev/null; then
        command -v "$c"; return 0
      fi
      if [ "$major" -eq "$min_major" ] && [ "$minor" -ge "$min_minor" ] 2>/dev/null; then
        command -v "$c"; return 0
      fi
    fi
  done
  return 1
}

any_python() {
  local c
  for c in python3.13 python3.12 python3.11 python3 python; do
    if have "$c"; then
      command -v "$c"
      return 0
    fi
  done
  return 1
}

install_node() {
  if have node && have npm; then
    ok "node $(node -v 2>/dev/null) / npm"
    return 0
  fi
  log "node/npm not found; trying package manager"
  OS="$(uname -s)"
  if [ "$OS" = "Darwin" ] && have brew; then
    brew install node >/dev/null 2>&1 || true
  elif have apt-get; then
    sudo_if env DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1 || true
    sudo_if env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs npm >/dev/null 2>&1 || true
  elif have dnf; then
    sudo_if dnf install -y nodejs npm >/dev/null 2>&1 || true
  fi
  if have node && have npm; then
    ok "node/npm installed"
    return 0
  fi
  warn "Could not install node/npm automatically."
  echo "EVE CLI needs Node.js. Install from https://nodejs.org then re-run."
}

clone_repo() {
  mkdir -p "$(dirname "$INSTALL_DIR")"
  if [ -d "$INSTALL_DIR/.git" ]; then
    log "Updating existing clone at $INSTALL_DIR"
    git -C "$INSTALL_DIR" fetch origin "$BRANCH" || warn "git fetch failed"
    git -C "$INSTALL_DIR" checkout "$BRANCH" || warn "git checkout $BRANCH failed"
    if ! git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"; then
      warn "fast-forward failed; leaving local checkout as-is"
    fi
  elif [ -e "$INSTALL_DIR" ]; then
    die "Directory exists but is not a git repo: $INSTALL_DIR (use --dir)"
  else
    log "Cloning $REPO_URL -> $INSTALL_DIR (branch $BRANCH)"
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
  fi
  ok "repository $INSTALL_DIR"
}

copy_env_if_missing() {
  local src="$1" dest="$2"
  if [ -e "$dest" ]; then
    log "keep existing $dest (never overwrite, never invent API keys)"
    return 0
  fi
  if [ ! -f "$src" ]; then
    warn "missing env template $src"
    return 0
  fi
  cp "$src" "$dest"
  ok "env copy $(basename "$src") -> $dest"
}

venv_py() {
  local venv="$1"
  if [ -x "$venv/bin/python" ]; then
    echo "$venv/bin/python"
  elif [ -x "$venv/Scripts/python.exe" ]; then
    echo "$venv/Scripts/python.exe"
  fi
}

setup_fabric() {
  local src="$1"
  local fabric_py="$2"
  local venv="$src/.venv"
  local vpy
  vpy="$(venv_py "$venv" || true)"
  if [ -z "$vpy" ]; then
    log "creating fabric venv $venv with $fabric_py"
    "$fabric_py" -m venv "$venv" || die "failed to create $venv (need python3-venv)"
    vpy="$(venv_py "$venv")"
  fi
  log "fabric pip install -e .[dev]"
  "$vpy" -m pip install -U pip setuptools wheel
  "$vpy" -m pip install -e ".[dev]"
  if ! "$vpy" -m pip install -e ".[engines]"; then
    warn "engines extra failed in fabric venv (camel-oasis needs Python 3.11)"
  fi
}

setup_oasis() {
  local src="$1"
  local py311="$2"
  local venv="$src/mirofish/.venv"
  local req="$src/mirofish/backend/requirements.txt"
  local vpy
  if [ -z "$py311" ]; then
    warn "Python 3.11 not found. OASIS (camel-oasis==0.2.5) needs 3.10-3.11."
    warn "Create $venv with 3.11 then: pip install -r $req"
    return 0
  fi
  vpy="$(venv_py "$venv" || true)"
  if [ -z "$vpy" ]; then
    log "creating OASIS venv $venv with $py311"
    "$py311" -m venv "$venv" || die "failed to create $venv"
    vpy="$(venv_py "$venv")"
  fi
  "$vpy" -m pip install -U pip setuptools wheel
  "$vpy" -m pip install -r "$req"
  ok "OASIS venv $vpy"
}

build_eve() {
  local src="$1"
  if ! have node || ! have npm; then
    warn "skipping EVE build (node/npm missing)"
    return 0
  fi
  if [ ! -d "$src/eve" ]; then
    die "eve/ tree missing"
  fi
  local step=install
  if [ -f "$src/eve/package-lock.json" ]; then
    step=ci
  fi
  log "EVE: npm $step && npm run build"
  ( cd "$src/eve" && npm "$step" && npm run build )
  if [ ! -f "$src/eve/bin/eve.js" ] && [ ! -f "$src/eve/dist/cli/main.js" ]; then
    die "EVE build did not produce eve/bin/eve.js"
  fi
  ok "EVE CLI built"
}

install_shim() {
  local src="$1"
  local vpy
  vpy="$(venv_py "$src/.venv")"
  [ -n "$vpy" ] || die "fabric venv python missing; cannot write eve-miro shim"
  local bindir="$HOME/.local/bin"
  mkdir -p "$bindir"
  local shim="$bindir/eve-miro"
  rm -f "$shim"
  cat > "$shim" <<SHIM
#!/usr/bin/env bash
unset PYTHONPATH PYTHONHOME
exec "$vpy" -m eve_miro.cli "\$@"
SHIM
  chmod +x "$shim"
  ok "shim $shim -> $vpy -m eve_miro.cli"
  export PATH="$bindir:$PATH"
  local rcfile=""
  case "${SHELL:-}" in
    */zsh) rcfile="$HOME/.zshrc" ;;
    */bash) rcfile="$HOME/.bashrc" ;;
  esac
  if [ -n "$rcfile" ]; then
    if ! grep -q ".local/bin" "$rcfile" 2>/dev/null; then
      echo "" >> "$rcfile"
      echo "# EVE-MIRO — ensure ~/.local/bin is on PATH" >> "$rcfile"
      echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$rcfile"
      ok "added ~/.local/bin to PATH in $rcfile"
    fi
  fi
}

print_success() {
  cat <<EOF

EVE-MIRO is installed.

  eve-miro           help
  eve-miro setup     LLM keys (ollama/openai/grok/deepseek/openrouter/azure/custom)
  eve-miro doctor    check 3.11 OASIS, node, eve.js
  eve-miro serve     MiroFish Flask :5001
  eve-miro run       tiny live loop (fail closed)
  eve-miro api       uvicorn :8000

Python split: fabric is 3.12+ at <src>/.venv ; OASIS is 3.11 at <src>/mirofish/.venv
Clone: $INSTALL_DIR
If eve-miro is not found, add ~/.local/bin to PATH or open a new shell.

EOF
}

main() {
  log "EVE-MIRO installer (non-interactive=$IS_INTERACTIVE)"
  install_git
  install_node

  PY311="$(find_py 3.11 || true)"
  FABRIC_PY="$(find_py_ge || true)"
  if [ -z "$FABRIC_PY" ]; then
    FABRIC_PY="$(any_python || true)"
    if [ -n "$FABRIC_PY" ]; then
      warn "No Python 3.12+ found; using $FABRIC_PY for fabric. OASIS still needs 3.11."
    fi
  fi
  if [ -z "$FABRIC_PY" ]; then
    die "Python 3 is required (prefer 3.12+ for fabric, 3.11 for OASIS)"
  fi
  if [ -z "$PY311" ]; then
    warn "Python 3.11 not found. OASIS (camel-oasis==0.2.5) needs 3.10-3.11."
  else
    ok "python 3.11: $PY311"
  fi
  ok "fabric python: $FABRIC_PY ($(py_ver "$FABRIC_PY"))"

  clone_repo
  cd "$INSTALL_DIR"

  if [ -f scripts/bootstrap.py ]; then
    log "running scripts/bootstrap.py (fabric venv + eve build + env copy)"
    if "$FABRIC_PY" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"; then
      "$FABRIC_PY" scripts/bootstrap.py || warn "bootstrap.py failed; continuing with explicit steps"
    else
      warn "bootstrap.py wants Python 3.12+; running explicit fabric steps"
    fi
  fi
  setup_fabric "$INSTALL_DIR" "$FABRIC_PY"
  setup_oasis "$INSTALL_DIR" "$PY311"
  build_eve "$INSTALL_DIR"
  copy_env_if_missing "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
  copy_env_if_missing "$INSTALL_DIR/mirofish/.env.example" "$INSTALL_DIR/mirofish/.env"
  install_shim "$INSTALL_DIR"

  if [ "$SKIP_SETUP" = true ] || [ "$IS_INTERACTIVE" = false ]; then
    log "skipping eve-miro setup (non-interactive or --skip-setup). Run: eve-miro setup"
  else
    if [ -x "$HOME/.local/bin/eve-miro" ]; then
      "$HOME/.local/bin/eve-miro" setup || warn "eve-miro setup exited non-zero"
    fi
  fi
  print_success
}

main "$@"
