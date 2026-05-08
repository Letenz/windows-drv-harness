#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Step 03 — Build the WinDbg extension DLL (windbgmcpExt.dll).

.DESCRIPTION
    Invokes MSBuild against third_party\windbg-ext-mcp\extension. If MSBuild is
    not available, this step is skipped with a warning; the user can instead
    download a prebuilt release from GitHub.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RepoRoot
)

$ErrorActionPreference = 'Stop'

$extDir = Join-Path $RepoRoot 'third_party\windbg-ext-mcp\extension'
if (-not (Test-Path $extDir)) {
    throw "Extension directory missing: $extDir. Did submodule init run?"
}

$msBuild = $env:DRIVER_HARNESS_MSBUILD
if (-not $msBuild -or -not (Test-Path $msBuild)) {
    Write-Host "MSBuild not available. Attempting to download prebuilt DLL from GitHub release..." -ForegroundColor Yellow
    # TODO (v0.2): curl the latest release asset from Letenz/windbg-ext-mcp
    Write-Host "  (TODO) Prebuilt download not implemented yet. Falling back to manual instructions:" -ForegroundColor Yellow
    Write-Host "    1. Download windbgmcpExt.dll from https://github.com/Letenz/windbg-ext-mcp/releases"
    Write-Host "    2. Place it at: $RepoRoot\third_party\windbg-ext-mcp\extension\build\x64\Release\windbgmcpExt.dll"
    throw 'MSBuild missing and prebuilt download not implemented.'
}

# Locate .vcxproj / .sln (layout in upstream may evolve)
$solution = Get-ChildItem -Path $extDir -Filter '*.sln' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$project  = Get-ChildItem -Path $extDir -Filter '*.vcxproj' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$target = $null
if ($solution) { $target = $solution.FullName }
elseif ($project) { $target = $project.FullName }
if (-not $target) {
    throw "No .sln or .vcxproj found under $extDir"
}

Write-Host "Building $target with $msBuild ..."
& $msBuild $target /p:Configuration=Release /p:Platform=x64 /m /nologo
if ($LASTEXITCODE -ne 0) {
    throw "MSBuild failed with exit code $LASTEXITCODE"
}

# Locate the produced DLL
$dll = Get-ChildItem -Path $extDir -Filter 'windbgmcpExt.dll' -Recurse -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $dll) {
    throw 'Build finished but windbgmcpExt.dll not found.'
}

Write-Host "Built: $($dll.FullName) ($($dll.Length) bytes)" -ForegroundColor Green

# Export path for subsequent steps
[System.Environment]::SetEnvironmentVariable(
    'DRIVER_HARNESS_EXT_DLL', $dll.FullName, 'Process'
)
