# TheWeave installer (Windows, PowerShell) — fetches a tagged release from
# GitHub, sets up a venv, installs the package, runs the doctor as the
# success signal. Mirrors install-weave.sh.
#
# Usage (PowerShell 5.1+ / PowerShell 7):
#   irm https://github.com/TheWeaveSC/theweave/releases/latest/download/install-weave.ps1 | iex
#   # or, with overrides:
#   $env:WEAVE_VERSION="0.4.0"; $env:WEAVE_HOME="$HOME\theweave"; .\install-weave.ps1
#   # or, install from a local zip (preview / private-repo test path):
#   $env:WEAVE_ZIP="$HOME\Downloads\theweave-preview.zip"; .\install-weave.ps1
#
# No GitHub authentication required. The source zip is fetched from the
# public archive endpoint by default, or read from a local file if WEAVE_ZIP
# is set.
#
# Windows support is BETA: this installer mirrors the macOS/Linux one and is
# code-reviewed, but has had limited field testing on Windows. Please report
# issues at https://github.com/TheWeaveSC/theweave/issues
#
# PATH note: install-weave.sh symlinks weave-cli into ~/.local/bin when that
# dir is on PATH. Windows has no equivalent user-bin convention, and editing
# the user PATH from a piped installer is invasive — so this script prints
# the full weave-cli.exe path instead. Add $env:USERPROFILE\theweave\venv\Scripts
# to your PATH manually if you want `weave-cli` on the command line.

$ErrorActionPreference = "Stop"

$WeaveVersion = if ($env:WEAVE_VERSION) { $env:WEAVE_VERSION } else { "0.4.0" }
$WeaveHome    = if ($env:WEAVE_HOME)    { $env:WEAVE_HOME }    else { Join-Path $HOME "theweave" }
$WeaveRepo    = if ($env:WEAVE_REPO)    { $env:WEAVE_REPO }    else { "TheWeaveSC/theweave" }

function Info([string]$msg)  { Write-Host $msg }
function Ok([string]$msg)    { Write-Host "  [ok] $msg" -ForegroundColor Green }
function Warn2([string]$msg) { Write-Host "  [!]  $msg" -ForegroundColor Yellow }
function Fail([string]$msg)  { Write-Host "  [x]  $msg" -ForegroundColor Red; exit 1 }

Info ""
Info "TheWeave installer - v$WeaveVersion (Windows beta)"
Info ""
Info "[Preflight]"

# --- Resolve a Python >= 3.11 -------------------------------------------
$Python = $null
$candidates = @()
if ($env:PYTHON) { $candidates += $env:PYTHON }
$candidates += @("py -3.13", "py -3.12", "py -3.11", "python3.13", "python3.12", "python3.11", "python3", "python", "py -3")
foreach ($candidate in $candidates) {
    $parts = $candidate -split " "
    $exe = $parts[0]
    $extra = if ($parts.Length -gt 1) { $parts[1..($parts.Length - 1)] } else { @() }
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    try {
        $version = & $exe @extra -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null
    } catch { continue }
    if ($version -match '^3\.(1[1-9]|[2-9][0-9])$') {
        $Python = $candidate
        break
    }
}
if (-not $Python) { Fail "Python >= 3.11 not found. Install Python 3.11+ (python.org or `winget install Python.Python.3.12`) and retry." }
$PyParts = $Python -split " "
$PyExe = $PyParts[0]
$PyArgs = if ($PyParts.Length -gt 1) { $PyParts[1..($PyParts.Length - 1)] } else { @() }
$pyVersionString = (& $PyExe @PyArgs --version) 2>&1
Ok "Python: $Python ($pyVersionString)"

# --- Target dir (same safety semantics as install-weave.sh) --------------
Info ""
Info "[Target]"
if (Test-Path $WeaveHome) {
    if ([Environment]::UserInteractive -and -not $env:WEAVE_NONINTERACTIVE) {
        Warn2 "$WeaveHome already exists."
        $response = Read-Host "    Remove and reinstall? [y/N]"
        if ($response -match '^(y|yes)$') {
            Remove-Item -Recurse -Force $WeaveHome
        } else {
            Fail "Aborted - keep existing install or set WEAVE_HOME to a different path."
        }
    } else {
        Fail "$WeaveHome already exists. Remove it, or set WEAVE_HOME=<other-path>."
    }
}
New-Item -ItemType Directory -Force -Path $WeaveHome | Out-Null
Ok "WEAVE_HOME: $WeaveHome"

# --- Source + extract -----------------------------------------------------
Info ""
Info "[Source]"
$tmpZip = Join-Path ([System.IO.Path]::GetTempPath()) "theweave-$WeaveVersion.zip"
if ($env:WEAVE_ZIP) {
    if (-not (Test-Path $env:WEAVE_ZIP)) { Fail "WEAVE_ZIP set but file not found: $($env:WEAVE_ZIP)" }
    Copy-Item $env:WEAVE_ZIP $tmpZip -Force
    Info "  local zip: $($env:WEAVE_ZIP)"
} else {
    $zipUrl = "https://github.com/$WeaveRepo/archive/refs/tags/v$WeaveVersion.zip"
    Info "  $zipUrl"
    try {
        Invoke-WebRequest -Uri $zipUrl -OutFile $tmpZip -UseBasicParsing
    } catch {
        Fail "Download failed. Check that release v$WeaveVersion exists at github.com/$WeaveRepo/releases."
    }
}
$tmpExtract = Join-Path ([System.IO.Path]::GetTempPath()) "theweave-extract-$([System.Guid]::NewGuid().ToString('N'))"
Expand-Archive -Path $tmpZip -DestinationPath $tmpExtract -Force
# The archive contains a single top-level dir (repo-tag); strip it like
# tar --strip-components=1 does.
$topLevel = Get-ChildItem -Path $tmpExtract -Directory | Select-Object -First 1
if (-not $topLevel) { Fail "Archive layout unexpected - no top-level directory found." }
Get-ChildItem -Path $topLevel.FullName -Force | Move-Item -Destination $WeaveHome
Remove-Item -Recurse -Force $tmpExtract
Remove-Item -Force $tmpZip
Ok "Extracted source to $WeaveHome"

# --- venv + install --------------------------------------------------------
Info ""
Info "[Install]"
& $PyExe @PyArgs -m venv (Join-Path $WeaveHome "venv")
if ($LASTEXITCODE -ne 0) { Fail "venv creation failed." }
Ok "Created venv at $WeaveHome\venv"

$VenvPython = Join-Path $WeaveHome "venv\Scripts\python.exe"
& $VenvPython -m pip install --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed." }
& $VenvPython -m pip install --quiet $WeaveHome
if ($LASTEXITCODE -ne 0) { Fail "package install failed." }
Ok "Installed theweave + dependencies into venv"

$WeaveCli = Join-Path $WeaveHome "venv\Scripts\weave-cli.exe"

# --- verify ----------------------------------------------------------------
Info ""
Info "[Verify]"
& $WeaveCli doctor *> $null
if ($LASTEXITCODE -eq 0) {
    Ok "weave-cli doctor: passed"
} else {
    Warn2 "weave-cli doctor reported issues - run `"$WeaveCli doctor`" to see details"
}

# --- done ------------------------------------------------------------------
Info ""
Info "TheWeave v$WeaveVersion installed. (Windows support is BETA - feedback welcome.)"
Info ""
Info "Next:"
Info "  1. Pick a starter vault (or point at your own):"
Info "       Copy-Item -Recurse $WeaveHome\personas\<starter-name> $HOME\my-vault"
Info "       $WeaveCli doctor --vault $HOME\my-vault"
Info ""
Info "  2. Register the MCP server with Claude Desktop:"
Info "       config file: %APPDATA%\Claude\claude_desktop_config.json"
Info "       see $WeaveHome\docs\claude-desktop-config.snippet.json"
Info "       (use $WeaveHome\venv\Scripts\python.exe as the command,"
Info "        and -m weave.mcp_server as the args)"
Info ""
Info "  3. Read the docs:"
Info "       $WeaveHome\README.md"
Info "       $WeaveHome\docs\architecture.md"
Info ""
