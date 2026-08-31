# In-tree Windows bootstrap: forwards args to scripts/bootstrap.py.
# One-liner installer (clone + shim) lives at repo-root install.ps1.
# Universal Windows install for EVE-MIRO. Forwards args to bootstrap.py.
# Example: .\scripts\install.ps1 --dry-run
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $RepoRoot
$script = Join-Path $RepoRoot "scripts\bootstrap.py"
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python $script @args
    exit $LASTEXITCODE
}
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 $script @args
    exit $LASTEXITCODE
}
Write-Error "Python 3.12+ is required. Install Python 3.12+ (PATH) or the py launcher."
exit 1
