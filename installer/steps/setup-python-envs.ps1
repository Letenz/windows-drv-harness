#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Step 04 — Create per-MCP Python venvs and install dependencies.

.DESCRIPTION
    Creates three venvs under each MCP package:
        third_party\vmware-mcp\.venv
        third_party\windbg-ext-mcp\.venv
        driver-harness-mcp\.venv
    and installs requirements / pyproject deps in each.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RepoRoot
)

$ErrorActionPreference = 'Stop'

$python = $env:DRIVER_HARNESS_PYTHON
if (-not $python -or -not (Test-Path $python)) {
    throw 'DRIVER_HARNESS_PYTHON not set or invalid. Re-run check-prereqs.ps1.'
}

function New-Venv {
    param([string]$Dir, [string]$InstallSpec)

    if (-not (Test-Path $Dir)) {
        Write-Host "  [SKIP] $Dir not present (submodule may not be initialized)" -ForegroundColor Yellow
        return
    }

    $venv = Join-Path $Dir '.venv'
    $pyExe = Join-Path $venv 'Scripts\python.exe'

    if (-not (Test-Path $pyExe)) {
        Write-Host "  Creating venv: $venv"
        & $python -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "venv creation failed for $Dir" }
    } else {
        Write-Host "  venv exists: $venv"
    }

    Write-Host "  Installing dependencies for $Dir ..."
    Push-Location $Dir
    try {
        & $pyExe -m pip install --upgrade pip --quiet
        if ($InstallSpec -eq 'pyproject') {
            & $pyExe -m pip install -e . --quiet
        } elseif ($InstallSpec -eq 'requirements') {
            $req = Join-Path $Dir 'requirements.txt'
            if (Test-Path $req) {
                & $pyExe -m pip install -r $req --quiet
            } else {
                Write-Host "    (no requirements.txt; skipping)"
            }
        }
        if ($LASTEXITCODE -ne 0) { throw "pip install failed in $Dir" }
    } finally {
        Pop-Location
    }
}

# vmware-mcp (uses requirements / pyproject; we try both)
$vmwareDir = Join-Path $RepoRoot 'third_party\vmware-mcp'
if (Test-Path (Join-Path $vmwareDir 'pyproject.toml')) {
    New-Venv -Dir $vmwareDir -InstallSpec 'pyproject'
} else {
    New-Venv -Dir $vmwareDir -InstallSpec 'requirements'
}

# windbg-ext-mcp
$windbgDir = Join-Path $RepoRoot 'third_party\windbg-ext-mcp'
if (Test-Path (Join-Path $windbgDir 'pyproject.toml')) {
    New-Venv -Dir $windbgDir -InstallSpec 'pyproject'
} else {
    New-Venv -Dir $windbgDir -InstallSpec 'requirements'
}

# driver-harness-mcp (our own)
$harnessDir = Join-Path $RepoRoot 'driver-harness-mcp'
New-Venv -Dir $harnessDir -InstallSpec 'pyproject'

Write-Host "Python envs ready." -ForegroundColor Green
