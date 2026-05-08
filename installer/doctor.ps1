<#
.SYNOPSIS
    Diagnose the driver-harness-mcp environment.

.DESCRIPTION
    Runs read-only checks. Reports each item as OK / WARN / FAIL.
    Run this any time something seems off.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$repoRoot = Split-Path -Parent $PSScriptRoot
$results = @()

function Test-Item {
    param(
        [string]$Name,
        [scriptblock]$Test,
        [string]$OnFail = ''
    )
    try {
        $r = & $Test
        if ($r) {
            $script:results += [pscustomobject]@{ Name = $Name; Status = 'OK';   Detail = "$r" }
        } else {
            $script:results += [pscustomobject]@{ Name = $Name; Status = 'FAIL'; Detail = $OnFail }
        }
    } catch {
        $script:results += [pscustomobject]@{ Name = $Name; Status = 'FAIL'; Detail = "$($_.Exception.Message). $OnFail" }
    }
}

Write-Host "=== driver-harness-mcp doctor ===" -ForegroundColor Cyan
Write-Host "Repo: $repoRoot"
Write-Host ""

# Host tools
Test-Item 'Git'        { (Get-Command git -ErrorAction SilentlyContinue).Source } 'Install Git for Windows.'
Test-Item 'Python'     { (Get-Command python -ErrorAction SilentlyContinue).Source } 'Install Python 3.11+.'
Test-Item 'vmrun.exe'  {
    $cands = @($env:VMRUN_PATH,
               'C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe',
               'C:\Program Files\VMware\VMware Workstation\vmrun.exe')
    $cands | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
} 'Install VMware Workstation Pro or set VMRUN_PATH.'

# Submodules
Test-Item 'submodule: vmware-mcp'      { (Test-Path (Join-Path $repoRoot 'third_party\vmware-mcp\.git')) -or (Test-Path (Join-Path $repoRoot 'third_party\vmware-mcp\README.md')) } 'Run: git submodule update --init --recursive'
Test-Item 'submodule: windbg-ext-mcp'  { (Test-Path (Join-Path $repoRoot 'third_party\windbg-ext-mcp\.git')) -or (Test-Path (Join-Path $repoRoot 'third_party\windbg-ext-mcp\README.md')) } 'Run: git submodule update --init --recursive'

# Extension DLL — checks locations in priority order:
#   1. %ProgramData%\driver-harness-mcp\bin\windbgmcpExt.dll  (installed by install-windbg-ext.ps1)
#   2. <repo>\bin\windbgmcpExt.dll                             (shipped precompiled)
#   3. <repo>\third_party\windbg-ext-mcp\extension\...\windbgmcpExt.dll  (user -Build)
Test-Item 'windbgmcpExt.dll available' {
    $installed = Join-Path $env:ProgramData 'driver-harness-mcp\bin\windbgmcpExt.dll'
    if (Test-Path $installed) { return "installed: $installed" }

    $shipped = Join-Path $repoRoot 'bin\windbgmcpExt.dll'
    if (Test-Path $shipped) { return "bin/: $shipped" }

    $extDir = Join-Path $repoRoot 'third_party\windbg-ext-mcp\extension'
    if (Test-Path $extDir) {
        $hit = Get-ChildItem $extDir -Filter 'windbgmcpExt.dll' -Recurse -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($hit) { return "built: $($hit.FullName)" }
    }
    return $null
} 'Run installer\install.ps1 — it will copy bin\windbgmcpExt.dll into %ProgramData%\driver-harness-mcp\bin\.'

# VirtualKD registry
Test-Item 'HKLM VKD DebuggerType=2' {
    $v = Get-ItemProperty 'HKLM:\Software\VirtualKD-Redux\Monitor' -ErrorAction SilentlyContinue
    if ($v -and $v.DebuggerType -eq 2) { return "DebuggerType=2" }
    return $null
} 'Run installer\steps\write-registry.ps1 as Administrator.'

Test-Item 'HKLM VKD CustomDebuggerTemplate' {
    $v = Get-ItemProperty 'HKLM:\Software\VirtualKD-Redux\Monitor' -ErrorAction SilentlyContinue
    if ($v -and $v.CustomDebuggerTemplate -and $v.CustomDebuggerTemplate -match 'windbgmcpExt') {
        return $v.CustomDebuggerTemplate.Substring(0, [Math]::Min(120, $v.CustomDebuggerTemplate.Length)) + '...'
    }
    return $null
} 'CustomDebuggerTemplate missing or does not reference windbgmcpExt. Re-run install.ps1.'

# vmmon64 running?
Test-Item 'vmmon64.exe running' {
    $p = Get-Process vmmon64 -ErrorAction SilentlyContinue
    if ($p) { "PID $($p.Id)" } else { $null }
} 'Launch vmmon64.exe from your VirtualKD-Redux install (will UAC prompt).'

# windbgmcp pipe live?
Test-Item 'windbgmcp pipe live' {
    if (Test-Path '\\.\pipe\windbgmcp') { 'pipe exists' } else { $null }
} 'Pipe only appears once a guest VM is running and WinDbg has finished autoload. Try running an example.'

# Print
Write-Host ""
$colors = @{ 'OK' = 'Green'; 'WARN' = 'Yellow'; 'FAIL' = 'Red' }
foreach ($r in $results) {
    $c = $colors[$r.Status]
    Write-Host ("  [{0,4}] {1}" -f $r.Status, $r.Name) -ForegroundColor $c -NoNewline
    if ($r.Detail) { Write-Host "  ($($r.Detail))" -ForegroundColor DarkGray } else { Write-Host '' }
}
Write-Host ""

$fails = $results | Where-Object { $_.Status -eq 'FAIL' }
if ($fails.Count -gt 0) {
    Write-Host "Doctor found $($fails.Count) failure(s)." -ForegroundColor Red
    exit 1
} else {
    Write-Host "All checks passed." -ForegroundColor Green
}
