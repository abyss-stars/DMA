# Local assembly helper: copy assets/** into install/ for testing with the GUI.
# Kept ASCII-only on purpose: Windows PowerShell 5.1 decodes .ps1 as ANSI unless
# the file has a BOM, so non-ASCII text here would break parsing.
#
# Usage:
#   powershell -NoProfile -File tools/dev_install.ps1                  # version from git describe
#   powershell -NoProfile -File tools/dev_install.ps1 -Version v1.0.4  # explicit version
param(
    [string]$Version = "",
    [string]$Os = "win",
    [string]$Arch = "x86_64"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not $Version) {
    $Version = (git describe --tags --always --dirty 2>$null)
    if (-not $Version) { $Version = "v0.0.0-dev" }
}

$env:PYTHONIOENCODING = "utf-8"
Write-Host "build version: $Version (display only, not used by build)"

python tools/install.py $Version $Os $Arch
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
