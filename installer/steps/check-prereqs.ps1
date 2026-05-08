#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Step 01 — Verify host prerequisites for driver-harness-mcp.

.DESCRIPTION
    Checks for VMware Workstation, Visual Studio / MSBuild, Windows SDK,
    Python 3.11+, and Git. Reports missing pieces with install suggestions.
    Sets shared environment variables consumed by later steps.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RepoRoot
)

$ErrorActionPreference = 'Stop'
$script:Failures = @()

function Check-Command {
    param(
        [string]$Name,
        [string]$Cmd,
        [string]$Hint
    )
    $found = Get-Command $Cmd -ErrorAction SilentlyContinue
    if ($found) {
        Write-Host "  [OK] $Name -> $($found.Source)" -ForegroundColor Green
        return $true
    } else {
        Write-Host "  [XX] $Name missing. $Hint" -ForegroundColor Red
        $script:Failures += $Name
        return $false
    }
}

function Check-File {
    param(
        [string]$Name,
        [string]$Path,
        [string]$Hint,
        [string]$EnvVar = $null
    )
    if (Test-Path $Path) {
        Write-Host "  [OK] $Name -> $Path" -ForegroundColor Green
        if ($EnvVar) { [System.Environment]::SetEnvironmentVariable($EnvVar, $Path, 'Process') }
        return $true
    } else {
        Write-Host "  [XX] $Name not found at $Path. $Hint" -ForegroundColor Red
        $script:Failures += $Name
        return $false
    }
}

Write-Host "Checking host prerequisites..."

# Git
Check-Command -Name 'git'    -Cmd 'git'    -Hint 'Install Git for Windows: https://git-scm.com/' | Out-Null

# Python 3.11+
$pyExe = $env:DRIVER_HARNESS_PYTHON
if (-not $pyExe) {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) { $pyExe = $py.Source }
}
if ($pyExe -and (Test-Path $pyExe)) {
    $pyVer = & $pyExe --version 2>&1
    Write-Host "  [OK] Python -> $pyExe ($pyVer)" -ForegroundColor Green
    [System.Environment]::SetEnvironmentVariable('DRIVER_HARNESS_PYTHON', $pyExe, 'Process')
} else {
    Write-Host "  [XX] Python 3.11+ missing. Install from python.org or set DRIVER_HARNESS_PYTHON." -ForegroundColor Red
    $script:Failures += 'Python'
}

# VMware Workstation (vmrun.exe)
$vmrunCandidates = @(
    $env:VMRUN_PATH,
    "C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
    "C:\Program Files\VMware\VMware Workstation\vmrun.exe"
) | Where-Object { $_ }
$vmrunFound = $null
foreach ($c in $vmrunCandidates) {
    if (Test-Path $c) { $vmrunFound = $c; break }
}
if ($vmrunFound) {
    Write-Host "  [OK] vmrun.exe -> $vmrunFound" -ForegroundColor Green
    [System.Environment]::SetEnvironmentVariable('VMRUN_PATH', $vmrunFound, 'Process')
} else {
    Write-Host "  [XX] vmrun.exe not found. Install VMware Workstation Pro, or set VMRUN_PATH." -ForegroundColor Red
    $script:Failures += 'VMware Workstation'
}

# MSBuild (VS 2022)
$msBuild = $env:DRIVER_HARNESS_MSBUILD
if (-not $msBuild) {
    $msbuildCandidates = @(
        "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\MSBuild\Current\Bin\MSBuild.exe",
        "C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe",
        "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe",
        "C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\MSBuild\Current\Bin\MSBuild.exe"
    )
    foreach ($c in $msbuildCandidates) {
        if (Test-Path $c) { $msBuild = $c; break }
    }
}
if ($msBuild -and (Test-Path $msBuild)) {
    Write-Host "  [OK] MSBuild -> $msBuild" -ForegroundColor Green
    [System.Environment]::SetEnvironmentVariable('DRIVER_HARNESS_MSBUILD', $msBuild, 'Process')
} else {
    Write-Host "  [!!] MSBuild not found. You'll need this to build the WinDbg extension DLL." -ForegroundColor Yellow
    Write-Host "       Set DRIVER_HARNESS_MSBUILD or pass -SkipBuild to install.ps1 and use a prebuilt DLL." -ForegroundColor Yellow
}

# Windows SDK Debugging Tools (dbgeng.h, DbgX.Shell.exe)
$sdkDbgRoots = @(
    "C:\Program Files (x86)\Windows Kits\10\Include",
    "C:\Program Files (x86)\Windows Kits\10\Debuggers"
)
$sdkFound = $sdkDbgRoots | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($sdkFound) {
    Write-Host "  [OK] Windows SDK Debugging Tools -> $sdkFound" -ForegroundColor Green
} else {
    Write-Host "  [!!] Windows SDK Debugging Tools not detected." -ForegroundColor Yellow
    Write-Host "       Required to build the extension and typically for WinDbg itself." -ForegroundColor Yellow
}

# Report
Write-Host ""
if ($script:Failures.Count -gt 0) {
    Write-Host "Prerequisite check FAILED. Missing: $($script:Failures -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "Prerequisite check passed." -ForegroundColor Green
