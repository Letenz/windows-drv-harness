#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Step 02 — Initialize and update git submodules.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RepoRoot
)

$ErrorActionPreference = 'Stop'
Push-Location $RepoRoot
try {
    Write-Host "Updating submodules..."
    & git submodule update --init --recursive --force
    if ($LASTEXITCODE -ne 0) {
        throw "git submodule update failed with exit code $LASTEXITCODE"
    }
    Write-Host "Submodules initialized."
} finally {
    Pop-Location
}
