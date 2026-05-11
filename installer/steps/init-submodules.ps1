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

    $vmwarePatch = Join-Path $RepoRoot 'third_party\patches\vmware-mcp-structured-guest-args.patch'
    $vmwareRepo = Join-Path $RepoRoot 'third_party\vmware-mcp'
    if (Test-Path $vmwarePatch) {
        & git -C $vmwareRepo apply --check $vmwarePatch 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Applying driver-harness vmware-mcp patch..."
            & git -C $vmwareRepo apply $vmwarePatch
            if ($LASTEXITCODE -ne 0) {
                throw "failed to apply vmware-mcp patch"
            }
        } else {
            & git -C $vmwareRepo apply --reverse --check $vmwarePatch 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "vmware-mcp patch already applied."
            } else {
                throw "vmware-mcp patch does not apply cleanly; check third_party\patches."
            }
        }
    }

    Write-Host "Submodules initialized."
} finally {
    Pop-Location
}
