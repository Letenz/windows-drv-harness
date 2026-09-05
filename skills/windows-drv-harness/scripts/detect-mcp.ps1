$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$smoke = Join-Path $scriptDir "smoke-mcp-server.py"

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
  return $null
}

$python = Get-HealthyPython
$smokeResult = $null
if ($python) {
  $output = & $python.File @($python.Prefix) $smoke --server harness 2>&1
  $smokeResult = [pscustomobject]@{
    ok = ($LASTEXITCODE -eq 0)
    output = ($output | Out-String).Trim()
  }
}

$codex = Get-Command codex -ErrorAction SilentlyContinue
$codexText = ""
$codexListOk = $false
if ($codex) {
  $savedPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $codexText = (& $codex.Source mcp list 2>&1 | Out-String)
    $codexListOk = ($LASTEXITCODE -eq 0)
  } catch {
    $codexText = $_.Exception.Message
  } finally {
    $ErrorActionPreference = $savedPreference
  }
}

[pscustomobject]@{
  ok = [bool]($python -and $smokeResult.ok)
  healthy_python = $(if ($python) { $python.File } else { $null })
  python_args = $(if ($python) { $python.Prefix } else { @() })
  harness_protocol_smoke = $smokeResult
  codex_available = [bool]$codex
  codex_list_ok = $codexListOk
  codex_error = $(if ($codex -and -not $codexListOk) { $codexText.Trim() } else { $null })
  codex_registered = ($codexText -match "(?m)^\s*windows-drv-harness\s")
  next_action = $(if (-not $python) {
    "Install a healthy Python 3.10+ runtime."
  } elseif (-not $smokeResult.ok) {
    "Fix the harness MCP smoke-test error."
  } elseif ($codex -and -not $codexListOk) {
    "Repair the Codex CLI configuration, or register this server in another MCP client."
  } elseif ($codex -and -not ($codexText -match "(?m)^\s*windows-drv-harness\s")) {
    "Run register-mcp.ps1 -Apply."
  } else {
    "The harness MCP is ready."
  })
} | ConvertTo-Json -Depth 6
