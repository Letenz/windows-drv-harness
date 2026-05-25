$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillDir = Split-Path -Parent $scriptDir
$windbgMcp = Join-Path $skillDir "windbg-mcp\windbg-mcp.exe"
$vmwareMcpExe = Join-Path $skillDir "vmware-mcp\.venv\Scripts\vmware-mcp.exe"
$smokeScript = Join-Path $skillDir "scripts\smoke-mcp-server.py"
$codexConfig = Join-Path $env:USERPROFILE ".codex\config.toml"

function Get-CommandPathOrNull {
  param([string]$Name)
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

function Invoke-Text {
  param([string]$FilePath, [string[]]$Arguments)
  try {
    $output = & $FilePath @Arguments 2>&1
    return [pscustomobject]@{
      ok = ($LASTEXITCODE -eq 0)
      text = ($output | Out-String).Trim()
      exit_code = $LASTEXITCODE
    }
  } catch {
    return [pscustomobject]@{
      ok = $false
      text = $_.Exception.Message
      exit_code = $null
    }
  }
}

function Test-ContainsPath {
  param([string]$Text, [string]$Path)
  if ([string]::IsNullOrWhiteSpace($Text) -or [string]::IsNullOrWhiteSpace($Path)) {
    return $false
  }
  $normalizedText = $Text.ToLowerInvariant().Replace("/", "\")
  $normalizedPath = $Path.ToLowerInvariant().Replace("/", "\")
  return $normalizedText.Contains($normalizedPath)
}

$codexPath = Get-CommandPathOrNull "codex"
$claudePath = Get-CommandPathOrNull "claude"

$codexList = $null
if ($codexPath) {
  $codexList = Invoke-Text $codexPath @("mcp", "list")
}

$claudeList = $null
if ($claudePath) {
  $claudeList = Invoke-Text $claudePath @("mcp", "list")
}

$codexText = if ($codexList) { $codexList.text } else { "" }
$claudeText = if ($claudeList) { $claudeList.text } else { "" }

$windbgSmoke = $null
$vmwareSmoke = $null
try {
  if (Test-Path -LiteralPath $windbgMcp) {
    $windbgSmoke = Invoke-Text "py" @("-3", $smokeScript, "--server", "windbg")
  }
} catch {
  $windbgSmoke = [pscustomobject]@{ ok = $false; text = $_.Exception.Message; exit_code = $null }
}
try {
  if (Test-Path -LiteralPath $vmwareMcpExe) {
    $vmwareSmoke = Invoke-Text "py" @("-3", $smokeScript, "--server", "vmware")
  }
} catch {
  $vmwareSmoke = [pscustomobject]@{ ok = $false; text = $_.Exception.Message; exit_code = $null }
}

[pscustomobject]@{
  skill_dir = $skillDir
  local_binaries = [pscustomobject]@{
    windbg_mcp = [pscustomobject]@{
      path = $windbgMcp
      exists = Test-Path -LiteralPath $windbgMcp
    }
    vmware_mcp = [pscustomobject]@{
      path = $vmwareMcpExe
      exists = Test-Path -LiteralPath $vmwareMcpExe
    }
  }
  protocol_smoke = [pscustomobject]@{
    windbg_mcp = [pscustomobject]@{
      ok = if ($windbgSmoke) { $windbgSmoke.ok } else { $false }
      output = if ($windbgSmoke) { $windbgSmoke.text } else { "" }
    }
    vmware_mcp = [pscustomobject]@{
      ok = if ($vmwareSmoke) { $vmwareSmoke.ok } else { $false }
      output = if ($vmwareSmoke) { $vmwareSmoke.text } else { "" }
    }
  }
  codex = [pscustomobject]@{
    command = $codexPath
    config = $codexConfig
    config_exists = Test-Path -LiteralPath $codexConfig
    list_ok = if ($codexList) { $codexList.ok } else { $false }
    list_preview = if ($codexText.Length -gt 1200) { $codexText.Substring(0, 1200) } else { $codexText }
    registered = [pscustomobject]@{
      windbg_mcp = ($codexText -match "(?m)^\s*windows-drv-windbg-mcp\s" -or (Test-ContainsPath $codexText $windbgMcp))
      vmware_mcp = ($codexText -match "(?m)^\s*windows-drv-vmware-mcp\s" -or (Test-ContainsPath $codexText $vmwareMcpExe))
    }
  }
  claude = [pscustomobject]@{
    command = $claudePath
    list_ok = if ($claudeList) { $claudeList.ok } else { $false }
    list_preview = if ($claudeText.Length -gt 1200) { $claudeText.Substring(0, 1200) } else { $claudeText }
    registered = [pscustomobject]@{
      windbg_mcp = ($claudeText -match "windows-drv-windbg-mcp" -or (Test-ContainsPath $claudeText $windbgMcp))
      vmware_mcp = ($claudeText -match "windows-drv-vmware-mcp" -or (Test-ContainsPath $claudeText $vmwareMcpExe))
    }
  }
  manual_codex_commands = @(
    "codex mcp add windows-drv-windbg-mcp -- `"$windbgMcp`"",
    "codex mcp add windows-drv-vmware-mcp -- `"$vmwareMcpExe`""
  )
  manual_claude_commands = @(
    "claude mcp add -s user windows-drv-windbg-mcp -- `"$windbgMcp`"",
    "claude mcp add -s user windows-drv-vmware-mcp -- `"$vmwareMcpExe`""
  )
} | ConvertTo-Json -Depth 8
