param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern("^[A-Za-z0-9._-]+$")]
  [string]$Name,
  [string]$OutputDirectory = (Join-Path $env:LOCALAPPDATA "windows-drv-harness\secrets")
)

$ErrorActionPreference = "Stop"
$secret = Read-Host "API key for $Name" -AsSecureString
if (-not $secret) { throw "Secret input was empty." }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$path = Join-Path $OutputDirectory ($Name + ".dpapi")
$encrypted = ConvertFrom-SecureString -SecureString $secret
$encoding = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText($path, $encrypted + "`r`n", $encoding)

[pscustomobject]@{
  ok = $true
  status = "secret_saved"
  name = $Name
  path = $path
  protection = "Windows DPAPI CurrentUser"
} | ConvertTo-Json -Depth 3
