#Requires -RunAsAdministrator
<#
.SYNOPSIS
    driver-harness-mcp installer.

.DESCRIPTION
    Runs each step under installer\steps\ in order. Stops on first failure.
    Re-running is safe — each step is idempotent.

.PARAMETER Build
    Compile windbgmcpExt.dll from third_party\windbg-ext-mcp source instead of
    using the precompiled bin\windbgmcpExt.dll. Requires Visual Studio 2022 +
    C++ workload + Windows 10 SDK.

.PARAMETER SkipExt
    Skip installing the WinDbg extension entirely (advanced; you must already
    have a working DLL on disk).

.PARAMETER SkipRegistry
    Skip writing the VirtualKD-Redux registry preset.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\install.ps1
    # Default: uses bin\windbgmcpExt.dll (no compiler required).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\install.ps1 -Build
    # Builds windbgmcpExt.dll from third_party\windbg-ext-mcp source.
#>
[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$SkipExt,
    [switch]$SkipRegistry
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$stepsDir = Join-Path $PSScriptRoot 'steps'

Write-Host "=== driver-harness-mcp installer ===" -ForegroundColor Cyan
Write-Host "Repo root: $repoRoot"
Write-Host ""

$steps = @(
    @{ Name = '01 — Check prerequisites';       Script = 'check-prereqs.ps1';        Skip = $false        ; Args = @{} },
    @{ Name = '02 — Init submodules';           Script = 'init-submodules.ps1';      Skip = $false        ; Args = @{} },
    @{ Name = '03 — Install windbg extension';  Script = 'install-windbg-ext.ps1';   Skip = $SkipExt      ; Args = @{ Build = [bool]$Build } },
    @{ Name = '04 — Set up Python envs';        Script = 'setup-python-envs.ps1';    Skip = $false        ; Args = @{} },
    @{ Name = '05 — Write VKD registry preset'; Script = 'write-registry.ps1';       Skip = $SkipRegistry ; Args = @{} }
)

foreach ($step in $steps) {
    if ($step.Skip) {
        Write-Host "[SKIP] $($step.Name)" -ForegroundColor DarkGray
        continue
    }

    Write-Host "[RUN ] $($step.Name)" -ForegroundColor Yellow
    $path = Join-Path $stepsDir $step.Script
    if (-not (Test-Path $path)) {
        throw "Step script missing: $path"
    }
    $stepArgs = @{ RepoRoot = $repoRoot } + $step.Args
    & $path @stepArgs
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "Step $($step.Name) exited with code $LASTEXITCODE"
    }
    Write-Host "[ OK ] $($step.Name)" -ForegroundColor Green
    Write-Host ""
}

Write-Host "=== Installation complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Run installer\doctor.ps1 to verify the environment"
Write-Host "  2. Configure your guest VM (see docs\configure-guest-vm.md)"
Write-Host "  3. Configure your AI client (see presets\mcp-client-config\)"
Write-Host "  4. Run the first example (examples\01-kernel-patch-bsod\)"
