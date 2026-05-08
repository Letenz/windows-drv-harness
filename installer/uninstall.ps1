#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Roll back driver-harness-mcp's host changes.

.DESCRIPTION
    Restores the VirtualKD-Redux registry keys to a sane default
    (DebuggerType=1, default custom template).
    Does NOT delete the repo, venvs, or built artifacts.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$keyHKLM = 'HKLM:\Software\VirtualKD-Redux\Monitor'
$keyHKCU = 'HKCU:\Software\VirtualKD-Redux\Monitor'
$defaultTemplate = 'cmd.exe /c "$(toolspath)\test.cmd" $(pipename)'

foreach ($key in @($keyHKLM, $keyHKCU)) {
    if (Test-Path $key) {
        Write-Host "Resetting $key ..."
        Set-ItemProperty -Path $key -Name 'DebuggerType' -Value 1 -Type DWord
        Set-ItemProperty -Path $key -Name 'CustomDebuggerTemplate' -Value $defaultTemplate
    } else {
        Write-Host "$key not present (nothing to reset)"
    }
}

Write-Host ""
Write-Host "Registry keys reset. To fully uninstall:" -ForegroundColor Yellow
Write-Host "  - Delete the repo directory"
Write-Host "  - Delete venvs in third_party\*\.venv and driver-harness-mcp\.venv"
Write-Host "  - Restart vmmon64.exe to pick up the rolled-back settings"
