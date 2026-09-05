param(
  [switch]$InstallRawVmwareMcp
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillDir = Split-Path -Parent $scriptDir
$repoRoot = (Resolve-Path (Join-Path $skillDir "..\..")).Path
$harnessMcp = Join-Path $scriptDir "harness_mcp.py"
$windbgMcp = Join-Path $skillDir "windbg-mcp\windbg-mcp.exe"
$mcpext = Join-Path $skillDir "windbg-mcp\mcpext.dll"
$manifestPath = Join-Path $skillDir "windbg-mcp\build-manifest.json"

function Get-HealthyPython {
  $candidates = @(
    [pscustomobject]@{ File = "py"; Prefix = @("-3.11") },
    [pscustomobject]@{ File = "py"; Prefix = @("-3.12") },
    [pscustomobject]@{ File = "py"; Prefix = @("-3") },
    [pscustomobject]@{ File = "python"; Prefix = @() }
  )
  foreach ($candidate in $candidates) {
    try {
      & $candidate.File @($candidate.Prefix) -c "import json,sys; assert sys.version_info >= (3,10)" *> $null
      if ($LASTEXITCODE -eq 0) {
        $command = Get-Command $candidate.File -ErrorAction Stop
        return [pscustomobject]@{ File = $command.Source; Prefix = @($candidate.Prefix) }
      }
    } catch {
    }
  }
  throw "No healthy Python 3.10+ runtime was found. A version-only check is insufficient; the standard library must import successfully."
}

foreach ($required in @($harnessMcp, $windbgMcp, $mcpext, $manifestPath)) {
  if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
    throw "Missing bundled harness component: $required"
  }
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$actualExeHash = (Get-FileHash -LiteralPath $windbgMcp -Algorithm SHA256).Hash
$actualDllHash = (Get-FileHash -LiteralPath $mcpext -Algorithm SHA256).Hash
if ($actualExeHash -ne $manifest.artifacts.'windbg-mcp.exe' -or $actualDllHash -ne $manifest.artifacts.'mcpext.dll') {
  throw "Bundled windbg-mcp artifact hash verification failed."
}

$python = Get-HealthyPython
& $python.File @($python.Prefix) -m py_compile (Join-Path $scriptDir "harness_core.py") $harnessMcp
if ($LASTEXITCODE -ne 0) { throw "Harness MCP Python validation failed." }

$vmwareMcpInstalled = $false
if ($InstallRawVmwareMcp) {
  $vmwareMcpDir = Join-Path $skillDir "vmware-mcp"
  $vmwarePyproject = Join-Path $vmwareMcpDir "pyproject.toml"
  if (-not (Test-Path -LiteralPath $vmwarePyproject)) {
    & git -C $repoRoot submodule update --init --recursive -- "skills/windows-drv-harness/vmware-mcp"
    if ($LASTEXITCODE -ne 0) { throw "Could not initialize vmware-mcp submodule." }
  }
  $venvPython = Join-Path $vmwareMcpDir ".venv\Scripts\python.exe"
  if (-not (Test-Path -LiteralPath $venvPython)) {
    & $python.File @($python.Prefix) -m venv (Join-Path $vmwareMcpDir ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create vmware-mcp virtual environment." }
  }
  & $venvPython -m pip install -e $vmwareMcpDir
  if ($LASTEXITCODE -ne 0) { throw "Could not install vmware-mcp." }
  $vmwareMcpInstalled = $true
}

[pscustomobject]@{
  ok = $true
  status = "local_mcp_ready"
  registered_in_client = $false
  python = $python.File
  python_args = $python.Prefix
  harness_mcp = $harnessMcp
  windbg_mcp = $windbgMcp
  mcpext = $mcpext
  windbg_mcp_version = $manifest.version
  windbg_mcp_source_commit = $manifest.commit
  raw_vmware_mcp_installed = $vmwareMcpInstalled
  next_action = "Run detect-mcp.ps1, then register-mcp.ps1 -Apply if the server is not registered."
} | ConvertTo-Json -Depth 5
