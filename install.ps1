# iex (irm https://raw.githubusercontent.com/fernandogarzaaa/EVE---MIRO/main/install.ps1)
# EVE-MIRO Windows installer
$ErrorActionPreference = "Stop"

if ($env:PYTHONPATH) {
  Write-Host "Ignoring inherited PYTHONPATH during install"
  Remove-Item Env:PYTHONPATH
}
if ($env:PYTHONHOME) {
  Write-Host "Ignoring inherited PYTHONHOME during install"
  Remove-Item Env:PYTHONHOME
}

$RepoUrl = "https://github.com/fernandogarzaaa/EVE---MIRO.git"
$Branch = "main"
$EveMiroHome = if ($env:EVE_MIRO_HOME) { $env:EVE_MIRO_HOME } else { Join-Path $env:USERPROFILE ".eve-miro" }
$InstallDir = $null
$SkipSetup = $false
$IsInteractive = [Environment]::UserInteractive -and -not [Console]::IsInputRedirected

function Show-Usage {
  Write-Host "EVE-MIRO installer"
  Write-Host ""
  Write-Host "Usage: install.ps1 [OPTIONS]"
  Write-Host ""
  Write-Host "Options:"
  Write-Host "  -Dir PATH         Clone/update destination (default: %USERPROFILE%\.eve-miro\src)"
  Write-Host "  -SkipSetup        Do not run eve-miro setup"
  Write-Host "  -Help             Show this help"
  Write-Host ""
  Write-Host "One-liners:"
  Write-Host "  curl -fsSL https://raw.githubusercontent.com/fernandogarzaaa/EVE---MIRO/main/install.sh | bash"
  Write-Host "  iex (irm https://raw.githubusercontent.com/fernandogarzaaa/EVE---MIRO/main/install.ps1)"
}

for ($i = 0; $i -lt $args.Count; $i++) {
  switch -Regex ($args[$i]) {
    "^--dir$|^-Dir$" { $InstallDir = $args[$i+1]; $i++; break }
    "^--skip-setup$|^-SkipSetup$" { $SkipSetup = $true; break }
    "^--help$|^-Help$|^-h$" { Show-Usage; exit 0 }
    default { Write-Error "Unknown option: $($args[$i])"; Show-Usage; exit 1 }
  }
}
if (-not $InstallDir) { $InstallDir = Join-Path $EveMiroHome "src" }

function Log([string]$m) { Write-Host "-> $m" }
function Ok([string]$m) { Write-Host "ok $m" }
function WarnMsg([string]$m) { Write-Warning $m }

function Test-Cmd([string]$name) {
  return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Install-Git {
  if (Test-Cmd "git") { Ok "git"; return }
  Log "git not found; trying winget"
  if (Test-Cmd "winget") {
    winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements | Out-Null
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
  }
  if (Test-Cmd "git") { Ok "git installed"; return }
  throw "git is required. Install from https://git-scm.com/download/win or: winget install Git.Git"
}

function Find-Python([string]$mm) {
  if (Test-Cmd "py") {
    try {
      $out = & py "-$mm" -c "import sys; print(sys.executable)" 2>$null
      if ($out) { return $out.Trim() }
    } catch {}
  }
  $candidates = @("python$mm", "python")
  foreach ($c in $candidates) {
    if (Test-Cmd $c) {
      $v = & $c -c "import sys; print(%s.%s % (sys.version_info[0], sys.version_info[1]))" 2>$null
      if ($v -and $v.Trim() -eq $mm) {
        return (Get-Command $c).Source
      }
    }
  }
  return $null
}

function Find-FabricPython {
  foreach ($mm in @("3.13","3.12")) {
    $p = Find-Python $mm
    if ($p) { return $p }
  }
  foreach ($c in @("python3","python")) {
    if (Test-Cmd $c) { return (Get-Command $c).Source }
  }
  return $null
}

function Venv-Python([string]$venv) {
  $unix = Join-Path $venv "bin/python"
  $win = Join-Path $venv "Scripts/python.exe"
  if (Test-Path $win) { return $win }
  if (Test-Path $unix) { return $unix }
  return $null
}

function Install-Node {
  if ((Test-Cmd "node") -and (Test-Cmd "npm")) { Ok "node/npm"; return }
  Log "node/npm not found; trying winget"
  if (Test-Cmd "winget") {
    winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements | Out-Null
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
  }
  if ((Test-Cmd "node") -and (Test-Cmd "npm")) { Ok "node/npm installed"; return }
  WarnMsg "Could not install node/npm. EVE needs Node.js from https://nodejs.org"
}

function Clone-Repo {
  $parent = Split-Path -Parent $InstallDir
  if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent | Out-Null }
  $gitDir = Join-Path $InstallDir ".git"
  if (Test-Path $gitDir) {
    Log "Updating existing clone at $InstallDir"
    git -C $InstallDir fetch origin $Branch
    git -C $InstallDir checkout $Branch
    try { git -C $InstallDir pull --ff-only origin $Branch }
    catch { WarnMsg "fast-forward failed; leaving local checkout as-is" }
  } elseif (Test-Path $InstallDir) {
    throw "Directory exists but is not a git repo: $InstallDir (use -Dir)"
  } else {
    Log "Cloning $RepoUrl -> $InstallDir"
    git clone --depth 1 --branch $Branch $RepoUrl $InstallDir
  }
  Ok "repository $InstallDir"
}

function Copy-EnvIfMissing([string]$src, [string]$dest) {
  if (Test-Path $dest) {
    Log "keep existing $dest (never overwrite, never invent API keys)"
    return
  }
  if (-not (Test-Path $src)) { WarnMsg "missing env template $src"; return }
  Copy-Item $src $dest
  Ok "env copy $(Split-Path $src -Leaf) -> $dest"
}

function Setup-Fabric([string]$src, [string]$fabricPy) {
  $venv = Join-Path $src ".venv"
  $vpy = Venv-Python $venv
  if (-not $vpy) {
    Log "creating fabric venv $venv with $fabricPy"
    & $fabricPy -m venv $venv
    $vpy = Venv-Python $venv
  }
  Log "fabric pip install -e .[dev]"
  & $vpy -m pip install -U pip setuptools wheel
  & $vpy -m pip install -e ".[dev]"
  try { & $vpy -m pip install -e ".[engines]" }
  catch { WarnMsg "engines extra failed in fabric venv (camel-oasis needs Python 3.11)" }
}

function Setup-Oasis([string]$src, [string]$py311) {
  $venv = Join-Path $src "mirofish/.venv"
  $req = Join-Path $src "mirofish/backend/requirements.txt"
  if (-not $py311) {
    WarnMsg "Python 3.11 not found. OASIS (camel-oasis==0.2.5) needs 3.10-3.11."
    return
  }
  $vpy = Venv-Python $venv
  if (-not $vpy) {
    Log "creating OASIS venv $venv with $py311"
    & $py311 -m venv $venv
    $vpy = Venv-Python $venv
  }
  & $vpy -m pip install -U pip setuptools wheel
  & $vpy -m pip install -r $req
  Ok "OASIS venv $vpy"
}

function Build-Eve([string]$src) {
  if (-not (Test-Cmd "node") -or -not (Test-Cmd "npm")) {
    WarnMsg "skipping EVE build (node/npm missing)"
    return
  }
  $eve = Join-Path $src "eve"
  if (-not (Test-Path $eve)) { throw "eve/ tree missing" }
  $step = "install"
  if (Test-Path (Join-Path $eve "package-lock.json")) { $step = "ci" }
  Log "EVE: npm $step && npm run build"
  Push-Location $eve
  try {
    & npm $step
    & npm run build
  } finally { Pop-Location }
  $binJs = Join-Path $eve "bin/eve.js"
  $distJs = Join-Path $eve "dist/cli/main.js"
  if (-not (Test-Path $binJs) -and -not (Test-Path $distJs)) {
    throw "EVE build did not produce eve/bin/eve.js"
  }
  Ok "EVE CLI built"
}

function Install-Shim([string]$src) {
  $vpy = Venv-Python (Join-Path $src ".venv")
  if (-not $vpy) { throw "fabric venv python missing; cannot write eve-miro shim" }
  $bindir = Join-Path $env:USERPROFILE ".eve-miro\bin"
  if (-not (Test-Path $bindir)) { New-Item -ItemType Directory -Path $bindir | Out-Null }
  $cmdPath = Join-Path $bindir "eve-miro.cmd"
  $shimBody = @"
@echo off
set PYTHONPATH=
set PYTHONHOME=
"$vpy" -m eve_miro.cli %*
"@
  Set-Content -Path $cmdPath -Value $shimBody -Encoding ASCII
  Ok "shim $cmdPath"
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  if (-not $userPath) { $userPath = "" }
  if ($userPath -notlike "*$bindir*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$bindir", "User")
    Ok "appended $bindir to user PATH"
  }
  $env:Path = "$bindir;$env:Path"
}

function Show-Success {
  Write-Host ""
  Write-Host "EVE-MIRO is installed."
  Write-Host ""
  Write-Host "  eve-miro           help"
  Write-Host "  eve-miro setup     LLM keys (ollama/openai/grok/deepseek/openrouter/azure/custom)"
  Write-Host "  eve-miro doctor    check 3.11 OASIS, node, eve.js"
  Write-Host "  eve-miro serve     MiroFish Flask :5001"
  Write-Host "  eve-miro run       tiny live loop (fail closed)"
  Write-Host "  eve-miro api       uvicorn :8000"
  Write-Host ""
  Write-Host "Python split: fabric is 3.12+ at <src>\.venv ; OASIS is 3.11 at <src>\mirofish\.venv"
  Write-Host "Clone: $InstallDir"
  Write-Host "If eve-miro is not found, open a new terminal so PATH updates apply."
}

Log "EVE-MIRO installer (interactive=$IsInteractive)"
Install-Git
Install-Node
$Py311 = Find-Python "3.11"
$FabricPy = Find-FabricPython
if (-not $FabricPy) { throw "Python 3 is required (prefer 3.12+ for fabric, 3.11 for OASIS)" }
if (-not $Py311) { WarnMsg "Python 3.11 not found. OASIS (camel-oasis==0.2.5) needs 3.10-3.11." }
else { Ok "python 3.11: $Py311" }
Ok "fabric python: $FabricPy"
Clone-Repo
Set-Location $InstallDir
$bootstrap = Join-Path $InstallDir "scripts/bootstrap.py"
if (Test-Path $bootstrap) {
  Log "running scripts/bootstrap.py"
  try { & $FabricPy $bootstrap } catch { WarnMsg "bootstrap.py failed; continuing with explicit steps" }
}
Setup-Fabric $InstallDir $FabricPy
Setup-Oasis $InstallDir $Py311
Build-Eve $InstallDir
Copy-EnvIfMissing (Join-Path $InstallDir ".env.example") (Join-Path $InstallDir ".env")
Copy-EnvIfMissing (Join-Path $InstallDir "mirofish/.env.example") (Join-Path $InstallDir "mirofish/.env")
Install-Shim $InstallDir
if ($SkipSetup -or -not $IsInteractive) {
  Log "skipping eve-miro setup (non-interactive or -SkipSetup). Run: eve-miro setup"
} else {
  $shim = Join-Path $env:USERPROFILE ".eve-miro\bin\eve-miro.cmd"
  if (Test-Path $shim) { & $shim setup }
}
Show-Success
