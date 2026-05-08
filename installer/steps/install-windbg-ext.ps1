#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Step 03 — Install windbgmcpExt.dll into a known location.

.DESCRIPTION
    Two modes:

    1. Default (fast path)
       Copy the precompiled DLL from bin\windbgmcpExt.dll. Verify against
       bin\windbgmcpExt.dll.sha256 to make sure the file in the repo has not
       been tampered with.

    2. -Build
       Invoke MSBuild against third_party\windbg-ext-mcp\extension and use
       the resulting DLL instead. Use this if you do not trust the binary
       in bin/, or if you have local modifications in the submodule.

    The chosen DLL is copied to:

        %ProgramData%\driver-harness-mcp\bin\windbgmcpExt.dll

    and its full path is exported via the DRIVER_HARNESS_EXT_DLL environment
    variable for subsequent installer steps (notably write-registry.ps1) to
    bake into the VKD-Redux CustomDebuggerTemplate.

.PARAMETER RepoRoot
    Absolute path to the repository root. Provided by install.ps1.

.PARAMETER Build
    Build from source instead of using bin\windbgmcpExt.dll.

.PARAMETER MSBuild
    Optional override for the path to MSBuild.exe. If not set, the script
    will look at $env:DRIVER_HARNESS_MSBUILD, then try `vswhere`.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RepoRoot,
    [switch]$Build,
    [string]$MSBuild
)

$ErrorActionPreference = 'Stop'

# ---- target install path ---------------------------------------------------
$installDir = Join-Path $env:ProgramData 'driver-harness-mcp\bin'
$installDll = Join-Path $installDir 'windbgmcpExt.dll'
New-Item -ItemType Directory -Path $installDir -Force | Out-Null

# ---- helper: compute sha256 ------------------------------------------------
function Get-Sha256Lower([string]$Path) {
    (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower()
}

# ---- pick source DLL -------------------------------------------------------
if ($Build) {
    Write-Host "Mode: BUILD from source" -ForegroundColor Cyan
    $extDir = Join-Path $RepoRoot 'third_party\windbg-ext-mcp\extension'
    if (-not (Test-Path $extDir)) {
        throw "Submodule not initialized: $extDir. Run installer\steps\init-submodules.ps1 first."
    }

    # MSBuild discovery
    if (-not $MSBuild) {
        if ($env:DRIVER_HARNESS_MSBUILD -and (Test-Path $env:DRIVER_HARNESS_MSBUILD)) {
            $MSBuild = $env:DRIVER_HARNESS_MSBUILD
        } else {
            $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
            if (Test-Path $vswhere) {
                $vsRoot = & $vswhere -latest -products '*' `
                    -requires Microsoft.Component.MSBuild `
                    -property installationPath 2>$null
                if ($vsRoot) {
                    $candidate = Join-Path $vsRoot 'MSBuild\Current\Bin\MSBuild.exe'
                    if (Test-Path $candidate) { $MSBuild = $candidate }
                }
            }
        }
    }
    if (-not $MSBuild -or -not (Test-Path $MSBuild)) {
        throw "MSBuild.exe not found. Pass -MSBuild <path> or set DRIVER_HARNESS_MSBUILD."
    }
    Write-Host "  MSBuild: $MSBuild"

    $proj = Join-Path $extDir 'windbgmcpExt.vcxproj'
    if (-not (Test-Path $proj)) {
        # fall back to recursive search if upstream layout changes
        $proj = (Get-ChildItem -Path $extDir -Filter '*.vcxproj' -Recurse |
                 Select-Object -First 1).FullName
    }
    if (-not $proj) { throw "No .vcxproj found under $extDir" }
    Write-Host "  Project: $proj"

    & $MSBuild $proj /t:Rebuild /p:Configuration=Release /p:Platform=x64 /m /nologo
    if ($LASTEXITCODE -ne 0) {
        throw "MSBuild failed with exit code $LASTEXITCODE"
    }

    $built = Get-ChildItem -Path $extDir -Filter 'windbgmcpExt.dll' -Recurse |
             Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $built) { throw "Build succeeded but windbgmcpExt.dll not found." }
    $sourceDll = $built.FullName
    Write-Host "  Built: $sourceDll ($($built.Length) bytes)"

} else {
    Write-Host "Mode: USE PRECOMPILED bin\windbgmcpExt.dll" -ForegroundColor Cyan
    $sourceDll  = Join-Path $RepoRoot 'bin\windbgmcpExt.dll'
    $sourceHash = Join-Path $RepoRoot 'bin\windbgmcpExt.dll.sha256'

    if (-not (Test-Path $sourceDll)) {
        throw "Precompiled DLL missing: $sourceDll`nUse -Build to compile from source instead."
    }
    if (Test-Path $sourceHash) {
        $expected = ((Get-Content $sourceHash -Raw) -split '\s+')[0].ToLower()
        $actual   = Get-Sha256Lower $sourceDll
        if ($expected -ne $actual) {
            throw "SHA256 mismatch for $sourceDll`n  expected: $expected`n  actual:   $actual"
        }
        Write-Host "  SHA256 verified: $actual"
    } else {
        Write-Warning "No SHA256 file at $sourceHash — skipping integrity check."
    }
    Write-Host "  Source: $sourceDll ($((Get-Item $sourceDll).Length) bytes)"
}

# ---- copy to install dir ---------------------------------------------------
# If WinDbg has the destination DLL loaded, the copy will fail with "in use".
try {
    Copy-Item -Path $sourceDll -Destination $installDll -Force
} catch {
    Write-Host ""
    Write-Host "Failed to copy DLL into $installDir." -ForegroundColor Red
    Write-Host "This usually means a WinDbg session has it loaded." -ForegroundColor Yellow
    Write-Host "Run !mcpstop, then .unload windbgmcpExt in WinDbg, or close WinDbg," -ForegroundColor Yellow
    Write-Host "and re-run the installer." -ForegroundColor Yellow
    throw
}

Write-Host "Installed: $installDll" -ForegroundColor Green

# ---- export for downstream steps ------------------------------------------
$env:DRIVER_HARNESS_EXT_DLL = $installDll
[System.Environment]::SetEnvironmentVariable(
    'DRIVER_HARNESS_EXT_DLL', $installDll, 'Process'
)
