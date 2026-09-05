param(
  [string]$Target,
  [string]$ConfigPath = $(
    if ($env:WINDOWS_DRV_HARNESS_CONFIG) {
      $env:WINDOWS_DRV_HARNESS_CONFIG
    } else {
      Join-Path $env:LOCALAPPDATA "windows-drv-harness\config.json"
    }
  )
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$cli = Join-Path $scriptDir "harness_cli.py"
$python = $null
foreach ($candidate in @("-3.11", "-3.12", "-3")) {
  try {
    & py $candidate -c "import json,sys; assert sys.version_info >= (3,10)" *> $null
    if ($LASTEXITCODE -eq 0) { $python = $candidate; break }
  } catch {
  }
}
if (-not $python) { throw "No healthy Python 3.10+ runtime was found." }
$arguments = @($python, $cli, "--config", $ConfigPath, "doctor")
if ($Target) { $arguments += @("--target", $Target) }
& py @arguments
exit $LASTEXITCODE
