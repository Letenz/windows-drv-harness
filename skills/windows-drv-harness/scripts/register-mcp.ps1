param(
  [ValidateSet("codex")]
  [string]$Client = "codex",

  [switch]$Apply,
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillDir = Split-Path -Parent $scriptDir
$windbgMcp = Join-Path $skillDir "windbg-mcp\windbg-mcp.exe"
$vmwareMcp = Join-Path $skillDir "vmware-mcp\.venv\Scripts\vmware-mcp.exe"

function Invoke-Checked {
  param([string]$FilePath, [string[]]$Arguments)
  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed: $FilePath $($Arguments -join ' ')"
  }
}

function Get-CodexListText {
  $cmd = Get-Command codex -ErrorAction SilentlyContinue
  if (-not $cmd) { return "" }
  $text = & $cmd.Source mcp list 2>&1 | Out-String
  return $text
}

function Test-ServerRegistered {
  param([string]$ListText, [string]$Name)
  return ($ListText -match "(?m)^\s*$([regex]::Escape($Name))\s")
}

if (-not (Test-Path -LiteralPath $windbgMcp)) {
  throw "Missing windbg MCP binary: $windbgMcp. Run install-mcp.ps1 first."
}
if (-not (Test-Path -LiteralPath $vmwareMcp)) {
  throw "Missing vmware MCP entrypoint: $vmwareMcp. Run install-mcp.ps1 first."
}

$codex = Get-Command codex -ErrorAction SilentlyContinue
if (-not $codex) {
  throw "Codex CLI was not found. Manual registration is required."
}

$commands = @(
  [pscustomobject]@{
    name = "windows-drv-windbg-mcp"
    args = @("mcp", "add", "windows-drv-windbg-mcp", "--", $windbgMcp)
    manual = "codex mcp add windows-drv-windbg-mcp -- `"$windbgMcp`""
  },
  [pscustomobject]@{
    name = "windows-drv-vmware-mcp"
    args = @("mcp", "add", "windows-drv-vmware-mcp", "--", $vmwareMcp)
    manual = "codex mcp add windows-drv-vmware-mcp -- `"$vmwareMcp`""
  }
)

if (-not $Apply) {
  [pscustomobject]@{
    applied = $false
    note = "Dry run only. Rerun with -Apply after user confirmation."
    manual_commands = $commands.manual
  } | ConvertTo-Json -Depth 4
  exit 0
}

$before = Get-CodexListText
$changes = @()
foreach ($entry in $commands) {
  $exists = Test-ServerRegistered $before $entry.name
  if ($exists -and -not $Force) {
    $changes += [pscustomobject]@{
      name = $entry.name
      action = "skipped"
      reason = "already registered"
    }
    continue
  }
  if ($exists -and $Force) {
    Invoke-Checked $codex.Source @("mcp", "remove", $entry.name)
  }
  Invoke-Checked $codex.Source $entry.args
  $changes += [pscustomobject]@{
    name = $entry.name
    action = "added"
  }
}

$after = Get-CodexListText
[pscustomobject]@{
  applied = $true
  changes = $changes
  list_preview = if ($after.Length -gt 1200) { $after.Substring(0, 1200) } else { $after }
} | ConvertTo-Json -Depth 6
