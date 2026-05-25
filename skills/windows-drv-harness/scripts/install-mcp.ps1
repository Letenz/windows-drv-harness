$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillDir = Split-Path -Parent $scriptDir
$repoRoot = (Resolve-Path (Join-Path $skillDir "..\..")).Path
$vmwareMcpDir = Join-Path $skillDir "vmware-mcp"
$vmwarePyproject = Join-Path $vmwareMcpDir "pyproject.toml"
$venvPython = Join-Path $vmwareMcpDir ".venv\Scripts\python.exe"
$windbgMcp = Join-Path $skillDir "windbg-mcp\windbg-mcp.exe"
$mcpext = Join-Path $skillDir "windbg-mcp\mcpext.dll"

function Invoke-Checked {
  param([string]$FilePath, [string[]]$Arguments)
  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed: $FilePath $($Arguments -join ' ')"
  }
}

function Get-PythonLauncher {
  $candidates = @(
    @("py", "-3.11"),
    @("py", "-3.12"),
    @("py", "-3")
  )

  foreach ($candidate in $candidates) {
    $exe = $candidate[0]
    $versionArg = $candidate[1]
    try {
      & $exe $versionArg --version *> $null
      if ($LASTEXITCODE -eq 0) {
        return $candidate
      }
    } catch {
      continue
    }
  }

  try {
    & python --version *> $null
    if ($LASTEXITCODE -eq 0) {
      return @("python")
    }
  } catch {
  }

  throw "Python 3.10+ was not found. Install Python, then rerun install-mcp.ps1."
}

if (-not (Test-Path -LiteralPath $windbgMcp)) {
  throw "Missing bundled windbg-mcp.exe: $windbgMcp"
}
if (-not (Test-Path -LiteralPath $mcpext)) {
  throw "Missing bundled mcpext.dll: $mcpext"
}

if (-not (Test-Path -LiteralPath $vmwarePyproject)) {
  $git = Get-Command git -ErrorAction SilentlyContinue
  if (-not $git) {
    throw "vmware-mcp submodule is missing and git was not found."
  }
  Invoke-Checked $git.Source @(
    "-C", $repoRoot,
    "submodule", "update", "--init", "--recursive", "--",
    "skills/windows-drv-harness/vmware-mcp"
  )
}

$python = Get-PythonLauncher
if (-not (Test-Path -LiteralPath $venvPython)) {
  $venvArgs = @()
  if ($python.Length -gt 1) {
    $venvArgs += $python[1..($python.Length - 1)]
  }
  $venvArgs += @("-m", "venv", (Join-Path $vmwareMcpDir ".venv"))
  Invoke-Checked $python[0] $venvArgs
}

Invoke-Checked $venvPython @("-m", "pip", "install", "-U", "pip")
Invoke-Checked $venvPython @("-m", "pip", "install", "-e", $vmwareMcpDir)

[pscustomobject]@{
  skill_dir = $skillDir
  registered_in_client = $false
  note = "Local MCP tooling is prepared only. Run detect-mcp.ps1, then register-mcp.ps1 -Apply after user confirmation to add servers to Codex MCP list."
  windbg_mcp_exists = Test-Path -LiteralPath $windbgMcp
  mcpext_exists = Test-Path -LiteralPath $mcpext
  vmware_mcp_dir = $vmwareMcpDir
  vmware_mcp_venv_python = $venvPython
  vmware_mcp_installed = Test-Path -LiteralPath $venvPython
} | ConvertTo-Json -Depth 4
