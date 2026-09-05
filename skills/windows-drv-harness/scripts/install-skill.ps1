param(
  [string]$SourceSkillDir = (Split-Path -Parent $PSScriptRoot),
  [string]$Destination = (Join-Path $env:USERPROFILE ".codex\skills\windows-drv-harness"),
  [switch]$Apply
)

$ErrorActionPreference = "Stop"
$source = (Resolve-Path -LiteralPath $SourceSkillDir).Path
$plan = [pscustomobject]@{
  source = $source
  destination = $Destination
  active_config = (Join-Path $env:LOCALAPPDATA "windows-drv-harness\config.json")
  copies_active_config = $false
}
if (-not $Apply) {
  [pscustomobject]@{
    ok = $true
    applied = $false
    plan = $plan
    next_action = "Rerun with -Apply to update the installed skill."
  } | ConvertTo-Json -Depth 4
  exit 0
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$destinationResolved = (Resolve-Path -LiteralPath $Destination).Path
$legacyHosts = @(Get-CimInstance Win32_Process -Filter "Name='windbg-mcp.exe'" -ErrorAction SilentlyContinue |
  Where-Object {
    ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($destinationResolved, [StringComparison]::OrdinalIgnoreCase)) -or
    ($_.CommandLine -and $_.CommandLine.Contains($destinationResolved))
  })
foreach ($process in $legacyHosts) {
  Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
}
if ($legacyHosts.Count -gt 0) { Start-Sleep -Milliseconds 300 }
foreach ($file in @(
  "SKILL.md",
  "windows-drv-harness.config.example.json",
  "windows-drv-harness.config.schema.json"
)) {
  Copy-Item -LiteralPath (Join-Path $source $file) -Destination (Join-Path $Destination $file) -Force
}
$pendingFiles = @()
$runtimeOverrides = @()
foreach ($directory in @("scripts", "references", "windbg-mcp")) {
  $target = Join-Path $Destination $directory
  New-Item -ItemType Directory -Force -Path $target | Out-Null
  $sourceDirectory = Join-Path $source $directory
  foreach ($item in Get-ChildItem -LiteralPath $sourceDirectory -Recurse -File) {
    $relative = $item.FullName.Substring($sourceDirectory.Length).TrimStart('\')
    $destinationFile = Join-Path $target $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destinationFile) | Out-Null
    try {
      Copy-Item -LiteralPath $item.FullName -Destination $destinationFile -Force
    } catch [IO.IOException] {
      $pendingFiles += $relative
      if ($directory -eq "windbg-mcp" -and $relative -eq "windbg-mcp.exe") {
        $sidecar = Join-Path $target "windbg-mcp-v2.exe"
        Copy-Item -LiteralPath $item.FullName -Destination $sidecar -Force
        $runtimeOverrides += $sidecar
      }
    }
  }
}

$legacyConfig = Join-Path $Destination "windows-drv-harness.config.json"
$legacyBackup = $null
if (Test-Path -LiteralPath $legacyConfig) {
  $migrationDir = Join-Path $env:LOCALAPPDATA "windows-drv-harness\migrations"
  New-Item -ItemType Directory -Force -Path $migrationDir | Out-Null
  $legacyBackup = Join-Path $migrationDir ("legacy-skill-config-{0}.json" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
  Move-Item -LiteralPath $legacyConfig -Destination $legacyBackup
}

[pscustomobject]@{
  ok = (($pendingFiles | Where-Object { $_ -ne "windbg-mcp.exe" }).Count -eq 0)
  applied = $true
  source = $source
  destination = $destinationResolved
  stopped_legacy_host_pids = @($legacyHosts | ForEach-Object { $_.ProcessId })
  pending_locked_files = $pendingFiles
  runtime_overrides = $runtimeOverrides
  active_config = $plan.active_config
  legacy_config_backup = $legacyBackup
  next_action = $(if (($pendingFiles | Where-Object { $_ -ne "windbg-mcp.exe" }).Count -gt 0) {
    "Restart clients holding the listed files, then rerun install-skill.ps1 -Apply."
  } elseif ($pendingFiles.Count -gt 0) {
    "The v2 sidecar is active now. Restart clients later and rerun this script to replace the legacy executable."
  } else {
    "Start a new agent session if skill metadata was already cached."
  })
} | ConvertTo-Json -Depth 4
