param(
  [string]$SkillDir = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "SilentlyContinue"

function Test-Admin {
  $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
  return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function First-ExistingPath {
  param([string[]]$Paths)
  foreach ($path in $Paths) {
    if (-not [string]::IsNullOrWhiteSpace($path) -and (Test-Path -LiteralPath $path)) {
      return (Resolve-Path -LiteralPath $path).Path
    }
  }
  return $null
}

function Read-Config {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return $null
  }
  try {
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
  } catch {
    return $null
  }
}

$skillDir = (Resolve-Path -LiteralPath $SkillDir).Path
$configPath = Join-Path $skillDir "windows-drv-harness.config.json"
$config = Read-Config -Path $configPath

$vmwareReg = Get-ItemProperty -Path "HKLM:\SOFTWARE\WOW6432Node\VMware, Inc.\VMware Workstation"
$virtualKdReg = Get-ItemProperty -Path "HKLM:\Software\VirtualKD-Redux"
$virtualKdMonitorReg = Get-ItemProperty -Path "HKLM:\Software\VirtualKD-Redux\Monitor"

$vmrunCandidates = @(
  $config.host.vmrun_path,
  $env:VMRUN_PATH,
  $(if ($vmwareReg.InstallPath) { Join-Path $vmwareReg.InstallPath "vmrun.exe" }),
  "C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
  "C:\Program Files\VMware\VMware Workstation\vmrun.exe"
)

$vmmonCandidates = @(
  $config.host.vmmon64_path,
  $env:WINDOWS_DRV_HARNESS_VMMON64,
  $env:VMMON64_PATH,
  $(if ($virtualKdReg.InstallPath) { Join-Path $virtualKdReg.InstallPath "vmmon64.exe" }),
  "C:\Program Files\VirtualKD-Redux\vmmon64.exe",
  "C:\Program Files (x86)\VirtualKD-Redux\vmmon64.exe"
)

$windbgCandidates = @(
  "C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\windbg.exe",
  "C:\Program Files\Windows Kits\10\Debuggers\x64\windbg.exe"
)

$vmmonProcesses = @(Get-Process vmmon64)
$debuggerProcesses = @(Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -in @("kd.exe", "cdb.exe", "windbg.exe", "windbgx.exe", "WinDbgX.exe") -and
    $_.CommandLine -match "mcpext\.dll|windbgmcpExt\.dll|!mcpext\.start|!mcpstart|\\\\\.\\pipe\\windbgmcp|com:pipe"
  } |
  Select-Object Name, ProcessId, CommandLine)

$pipes = @([System.IO.Directory]::EnumerateFiles("\\.\pipe\") |
  Where-Object { $_ -match "\\\\\.\\pipe\\kd_" -and $_ -notmatch "_virtualkd_svc_" })

$windbgMcpPipe = [System.IO.Directory]::EnumerateFiles("\\.\pipe\") -contains "\\.\pipe\windbgmcp"

$result = [ordered]@{
  skill_dir = $skillDir
  config_path = $configPath
  config_exists = [bool]$config
  is_admin = Test-Admin
  bundled = [ordered]@{
    windbg_mcp = Test-Path -LiteralPath (Join-Path $skillDir "windbg-mcp\windbg-mcp.exe")
    mcpext = Test-Path -LiteralPath (Join-Path $skillDir "windbg-mcp\mcpext.dll")
  }
  config = [ordered]@{
    vmx_path = $config.vm.vmx_path
    baseline_snapshot = $config.vm.baseline_snapshot
    guest_admin_user = $config.guest.admin_user
    guest_admin_password_present = -not [string]::IsNullOrWhiteSpace($config.guest.admin_password)
    vmrun_path = $config.host.vmrun_path
    vmmon64_path = $config.host.vmmon64_path
    symbols_path = $config.host.symbols_path
  }
  discovered = [ordered]@{
    vmrun_path = First-ExistingPath -Paths $vmrunCandidates
    vmmon64_path = First-ExistingPath -Paths $vmmonCandidates
    windbg_path = First-ExistingPath -Paths $windbgCandidates
    nt_symbol_path = $env:_NT_SYMBOL_PATH
  }
  virtualkd_monitor = [ordered]@{
    present = [bool]$virtualKdMonitorReg
    DebuggerType = $virtualKdMonitorReg.DebuggerType
    AutoInvokeDebugger = $virtualKdMonitorReg.AutoInvokeDebugger
    InitialBreakIn = $virtualKdMonitorReg.InitialBreakIn
    WaitForOS = $virtualKdMonitorReg.WaitForOS
    CustomDebuggerTemplate = $virtualKdMonitorReg.CustomDebuggerTemplate
  }
  processes = [ordered]@{
    vmmon64_count = $vmmonProcesses.Count
    vmmon64_pids = @($vmmonProcesses | ForEach-Object { $_.Id })
    harness_debuggers = $debuggerProcesses
  }
  pipes = [ordered]@{
    kd_main_pipes = $pipes
    windbgmcp_exists = $windbgMcpPipe
  }
}

$result | ConvertTo-Json -Depth 6
