#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Step 05 — Write VirtualKD-Redux Monitor registry preset to HKLM.

.DESCRIPTION
    Configures vmmon64.exe to:
      - DebuggerType = 2 (Custom)
      - CustomDebuggerTemplate = launches WinDbg Preview with -c .load + !mcpstart

    Detects DbgX.Shell.exe and the built extension DLL automatically. If either
    is missing, prints a clear error and bails (does not write a broken value).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RepoRoot
)

$ErrorActionPreference = 'Stop'

# 1. Find DbgX.Shell.exe (Microsoft Store install or sideload)
$dbgxCandidates = @(
    "C:\Program Files\WindowsApps\Microsoft.WinDbg_*\DbgX.Shell.exe",
    "$env:LOCALAPPDATA\Microsoft\WindowsApps\WinDbgX.exe",
    "$env:ProgramFiles\WindowsApps\Microsoft.WinDbg_*\DbgX.Shell.exe"
)
$dbgxFound = $null
foreach ($pattern in $dbgxCandidates) {
    $hit = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
    if ($hit) { $dbgxFound = $hit.FullName; break }
}
if (-not $dbgxFound) {
    Write-Host "  [XX] DbgX.Shell.exe not found in standard locations." -ForegroundColor Red
    Write-Host "       Set DRIVER_HARNESS_DBGX env var to the absolute path, then re-run." -ForegroundColor Red
    if ($env:DRIVER_HARNESS_DBGX -and (Test-Path $env:DRIVER_HARNESS_DBGX)) {
        $dbgxFound = $env:DRIVER_HARNESS_DBGX
    } else {
        throw 'DbgX.Shell.exe not found.'
    }
}
Write-Host "  DbgX.Shell.exe -> $dbgxFound"

# 2. Find windbgmcpExt.dll
$dllPath = $env:DRIVER_HARNESS_EXT_DLL
if (-not $dllPath -or -not (Test-Path $dllPath)) {
    $extDir = Join-Path $RepoRoot 'third_party\windbg-ext-mcp\extension'
    $hit = Get-ChildItem -Path $extDir -Filter 'windbgmcpExt.dll' -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($hit) { $dllPath = $hit.FullName }
}
if (-not $dllPath -or -not (Test-Path $dllPath)) {
    throw "windbgmcpExt.dll not found.`n" +
          "  Run installer\steps\install-windbg-ext.ps1 first,`n" +
          "  or point DRIVER_HARNESS_EXT_DLL at an existing DLL."
}
Write-Host "  windbgmcpExt.dll -> $dllPath"

# 3. Build the CustomDebuggerTemplate string
$template = '"' + $dbgxFound + '" -k com:pipe,port=$(pipename),resets=0,reconnect -d -c ".load ' + $dllPath + '; !mcpstart"'

Write-Host "  Template: $template" -ForegroundColor DarkGray

# 4. Stop vmmon64 before changing registry. It reads these values at launch.
$vmmonToRestart = $null
$runningVmmon = Get-Process -Name vmmon64 -ErrorAction SilentlyContinue
if ($runningVmmon) {
    $vmmonToRestart = ($runningVmmon | Where-Object { $_.Path } | Select-Object -First 1).Path
    Write-Host "  Stopping vmmon64.exe before registry write..." -ForegroundColor Yellow
    $runningVmmon | Stop-Process -Force
    Start-Sleep -Seconds 1
}

# 5. Backup current values (best-effort)
$backupFile = Join-Path $RepoRoot ('installer\.vkd-registry-backup-' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.reg')
$null = New-Item -ItemType Directory -Path (Split-Path $backupFile) -Force
& reg export 'HKLM\Software\VirtualKD-Redux\Monitor' $backupFile /y 2>&1 | Out-Null
if (Test-Path $backupFile) {
    Write-Host "  Backup written: $backupFile"
}

# 6. Write
$key = 'HKLM:\Software\VirtualKD-Redux\Monitor'
if (-not (Test-Path $key)) {
    New-Item -Path $key -Force | Out-Null
}
Set-ItemProperty -Path $key -Name 'DebuggerType' -Value 2 -Type DWord
Set-ItemProperty -Path $key -Name 'CustomDebuggerTemplate' -Value $template
Set-ItemProperty -Path $key -Name 'AutoInvokeDebugger' -Value 1 -Type DWord
Set-ItemProperty -Path $key -Name 'InitialBreakIn' -Value 1 -Type DWord
Set-ItemProperty -Path $key -Name 'WaitForOS' -Value 1 -Type DWord

# 7. Verify
$verify = Get-ItemProperty -Path $key
if ($verify.DebuggerType -ne 2) {
    throw "Verification failed: DebuggerType is $($verify.DebuggerType), expected 2"
}
Write-Host "  Verified: DebuggerType=2, CustomDebuggerTemplate set." -ForegroundColor Green

# 8. Restart vmmon64 if it was running before the registry change.
if ($vmmonToRestart -and (Test-Path $vmmonToRestart)) {
    Write-Host "  Restarting vmmon64.exe so it reads the new registry values..." -ForegroundColor Yellow
    Start-Process -FilePath $vmmonToRestart -WindowStyle Hidden
} else {
    Write-Host ""
    Write-Host "  IMPORTANT: Start vmmon64.exe before reverting/starting the debug VM." -ForegroundColor Yellow
    Write-Host "  It must be running to observe VirtualKD and auto-launch WinDbg." -ForegroundColor Yellow
}
