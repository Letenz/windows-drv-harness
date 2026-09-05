param(
  [ValidateSet("codex")]
  [string]$Client = "codex",
  [switch]$Apply,
  [switch]$Force,
  [switch]$RemoveLegacyRaw
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$server = Join-Path $scriptDir "harness_mcp.py"

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
  throw "No healthy Python 3.10+ runtime was found."
}

if (-not (Test-Path -LiteralPath $server -PathType Leaf)) {
  throw "Missing harness MCP server: $server"
}
$codex = Get-Command codex -ErrorAction SilentlyContinue
if (-not $codex) { throw "Codex CLI was not found; register the printed command manually." }
$python = Get-HealthyPython
$name = "windows-drv-harness"
$serverArgs = @($python.Prefix) + @($server)
$manualParts = @("codex", "mcp", "add", $name, "--", ('"' + $python.File + '"')) + @($serverArgs | ForEach-Object { '"' + $_ + '"' })
$manual = $manualParts -join " "

$savedPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$before = & $codex.Source mcp list 2>&1 | Out-String
$listExitCode = $LASTEXITCODE
$ErrorActionPreference = $savedPreference
if ($listExitCode -ne 0) {
  throw "Codex MCP list failed. Repair the Codex CLI configuration first: $($before.Trim())"
}
$exists = $before -match "(?m)^\s*$([regex]::Escape($name))\s"
if (-not $Apply) {
  [pscustomobject]@{
    ok = $true
    applied = $false
    registered = $exists
    manual_command = $manual
    next_action = "Rerun with -Apply only when registration is intended."
  } | ConvertTo-Json -Depth 4
  exit 0
}

if ($exists -and $Force) {
  & $codex.Source mcp remove $name
  if ($LASTEXITCODE -ne 0) { throw "Could not remove existing $name registration." }
  $exists = $false
}
if (-not $exists) {
  $arguments = @("mcp", "add", $name, "--", $python.File) + $serverArgs
  & $codex.Source @arguments
  if ($LASTEXITCODE -ne 0) { throw "Could not register $name." }
}
$removedLegacy = @()
if ($RemoveLegacyRaw) {
  foreach ($legacyName in @("windbg-mcp", "vmware")) {
    if ($before -match "(?m)^\s*$([regex]::Escape($legacyName))\s") {
      & $codex.Source mcp remove $legacyName
      if ($LASTEXITCODE -ne 0) { throw "Could not remove legacy MCP registration: $legacyName" }
      $removedLegacy += $legacyName
    }
  }
}
$savedPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$after = & $codex.Source mcp list 2>&1 | Out-String
$afterExitCode = $LASTEXITCODE
$ErrorActionPreference = $savedPreference
if ($afterExitCode -ne 0) { throw "Codex MCP list failed after registration." }
[pscustomobject]@{
  ok = $true
  applied = $true
  action = $(if ($exists) { "kept" } else { "added" })
  registered = ($after -match "(?m)^\s*$([regex]::Escape($name))\s")
  server_name = $name
  removed_legacy_raw_servers = $removedLegacy
  next_action = "Restart or reload the MCP client if the new tools are not visible yet."
} | ConvertTo-Json -Depth 4
