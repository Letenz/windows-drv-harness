param(
  [string]$ConfigPath = $(
    if ($env:WINDOWS_DRV_HARNESS_CONFIG) {
      $env:WINDOWS_DRV_HARNESS_CONFIG
    } else {
      Join-Path $env:LOCALAPPDATA "windows-drv-harness\config.json"
    }
  ),
  [string]$SkillDir = (Split-Path -Parent $PSScriptRoot),
  [switch]$Elevated,
  [string]$ResultPath
)

$ErrorActionPreference = "Stop"

function Test-Administrator {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Quote-Argument {
  param([string]$Value)
  return '"' + $Value.Replace('"', '\"') + '"'
}

if (-not (Test-Administrator)) {
  if ($Elevated) {
    throw "Elevation was requested, but the child process is still not Administrator."
  }
  $resultFile = Join-Path $env:TEMP ("windows-drv-harness-setup-{0}.json" -f [guid]::NewGuid().ToString("N"))
  $arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", (Quote-Argument $PSCommandPath),
    "-ConfigPath", (Quote-Argument $ConfigPath),
    "-SkillDir", (Quote-Argument $SkillDir),
    "-ResultPath", (Quote-Argument $resultFile),
    "-Elevated"
  ) -join " "
  $process = Start-Process -FilePath "powershell.exe" -Verb RunAs -WindowStyle Hidden -PassThru -ArgumentList $arguments
  $process.WaitForExit()
  if (Test-Path -LiteralPath $resultFile) {
    Get-Content -LiteralPath $resultFile -Raw -Encoding UTF8
    Remove-Item -LiteralPath $resultFile -Force
  }
  exit $process.ExitCode
}

trap {
  $failure = [pscustomobject]@{
    ok = $false
    status = "host_setup_failed"
    message = $_.Exception.Message
    next_action = "Fix this host setup error and rerun setup-host.ps1."
  } | ConvertTo-Json -Depth 4
  if ($ResultPath) {
    $failureEncoding = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($ResultPath, $failure + "`r`n", $failureEncoding)
  }
  Write-Error $_
  exit 1
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
  throw "User config does not exist: $ConfigPath. Run configure_target.py first."
}

$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($config.version -ne 2 -or -not $config.host) {
  throw "setup-host.ps1 requires a version 2 user config."
}

function First-ExistingFile {
  param([object[]]$Candidates)
  foreach ($candidate in $Candidates) {
    if ($candidate -and -not [string]::IsNullOrWhiteSpace([string]$candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
      return (Resolve-Path -LiteralPath $candidate).Path
    }
  }
  return $null
}

Add-Type @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

public static class HarnessProcessPath {
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint access, bool inherit, int processId);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool QueryFullProcessImageName(
        IntPtr process, int flags, StringBuilder path, ref int size);

    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(IntPtr handle);

    public static string Query(int processId) {
        IntPtr handle = OpenProcess(0x1000, false, processId);
        if (handle == IntPtr.Zero) return null;
        try {
            var path = new StringBuilder(32768);
            int size = path.Capacity;
            return QueryFullProcessImageName(handle, 0, path, ref size)
                ? path.ToString()
                : null;
        } finally {
            CloseHandle(handle);
        }
    }
}
'@

$vmware = Get-ItemProperty -Path "HKLM:\SOFTWARE\WOW6432Node\VMware, Inc.\VMware Workstation" -ErrorAction SilentlyContinue
$monitor = Get-ItemProperty -Path "HKLM:\Software\VirtualKD-Redux\Monitor" -ErrorAction SilentlyContinue
$runningVmmon = @(Get-CimInstance Win32_Process -Filter "Name='vmmon64.exe'" -ErrorAction SilentlyContinue)
$runningVmmonProcess = @(Get-Process vmmon64 -ErrorAction SilentlyContinue)
$queriedVmmonPath = $(if ($runningVmmonProcess.Count -gt 0) { [HarnessProcessPath]::Query($runningVmmonProcess[0].Id) })

$vmrun = First-ExistingFile @(
  $config.host.vmrun_path,
  $env:VMRUN_PATH,
  $(if ($vmware.InstallPath) { Join-Path $vmware.InstallPath "vmrun.exe" }),
  "C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
  "C:\Program Files\VMware\VMware Workstation\vmrun.exe"
)

$vmmon = First-ExistingFile @(
  $config.host.vmmon64_path,
  $env:WINDOWS_DRV_HARNESS_VMMON64,
  $env:VMMON64_PATH,
  $($runningVmmon | Select-Object -ExpandProperty ExecutablePath -First 1),
  $($runningVmmonProcess | Select-Object -ExpandProperty Path -First 1),
  $queriedVmmonPath,
  "C:\Program Files\VirtualKD-Redux\vmmon64.exe",
  "C:\Program Files (x86)\VirtualKD-Redux\vmmon64.exe"
)

$windbg = First-ExistingFile @(
  $config.host.windbg_path,
  $env:WINDBG_PATH,
  $(if ($monitor.ToolsPath) { Join-Path $monitor.ToolsPath "windbg.exe" }),
  "C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\windbg.exe",
  "C:\Program Files\Windows Kits\10\Debuggers\x64\windbg.exe"
)

$driverKit16 = Test-Path -LiteralPath "C:\Program Files (x86)\Windows Kits\10\build\bin\Microsoft.DriverKit.Build.Tasks.16.0.dll"
$driverKit17 = Test-Path -LiteralPath "C:\Program Files (x86)\Windows Kits\10\build\bin\Microsoft.DriverKit.Build.Tasks.17.0.dll"
$msbuildCandidates = @($config.host.msbuild_path, $env:MSBUILD_PATH)
if ($driverKit17) {
  $msbuildCandidates += @(
    "C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe",
    "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe",
    "D:\software\vs2022\MSBuild\Current\Bin\MSBuild.exe"
  )
}
if ($driverKit16) {
  $msbuildCandidates += @(
    "C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\MSBuild\Current\Bin\MSBuild.exe",
    "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\MSBuild\Current\Bin\MSBuild.exe"
  )
}
$msbuild = First-ExistingFile $msbuildCandidates

if (-not $vmrun) { throw "vmrun.exe was not found by bounded probing. Add host.vmrun_path to $ConfigPath." }
if (-not $vmmon) { throw "vmmon64.exe was not found by bounded probing. Add host.vmmon64_path to $ConfigPath." }
if (-not $windbg) { throw "Classic windbg.exe was not found. Add host.windbg_path to $ConfigPath." }
if (-not $msbuild) { throw "No MSBuild installation matches the installed WDK DriverKit tasks. Add host.msbuild_path to $ConfigPath." }

$skillDirResolved = (Resolve-Path -LiteralPath $SkillDir).Path
$mcpext = Join-Path $skillDirResolved "windbg-mcp\mcpext.dll"
if (-not (Test-Path -LiteralPath $mcpext -PathType Leaf)) {
  throw "Bundled mcpext.dll is missing: $mcpext"
}

$registryPath = "HKLM:\Software\VirtualKD-Redux\Monitor"
$template = "`"$windbg`" -b -c `".load $mcpext; !mcpext.start; g`" -k com:pipe,port=`$(pipename),resets=0,reconnect"
$needsRegistryChange = (
  -not $monitor -or
  $monitor.DebuggerType -ne 2 -or
  $monitor.AutoInvokeDebugger -ne 0 -or
  $monitor.InitialBreakIn -ne 1 -or
  $monitor.WaitForOS -ne 1 -or
  $monitor.CustomDebuggerTemplate -ne $template
)

if ($needsRegistryChange) {
  New-Item -Path $registryPath -Force | Out-Null
  Set-ItemProperty -Path $registryPath -Name DebuggerType -Type DWord -Value 2
  Set-ItemProperty -Path $registryPath -Name AutoInvokeDebugger -Type DWord -Value 0
  Set-ItemProperty -Path $registryPath -Name InitialBreakIn -Type DWord -Value 1
  Set-ItemProperty -Path $registryPath -Name WaitForOS -Type DWord -Value 1
  Set-ItemProperty -Path $registryPath -Name CustomDebuggerTemplate -Type String -Value $template
}

$vmmonProcesses = @(Get-Process vmmon64 -ErrorAction SilentlyContinue)
if ($needsRegistryChange -or $vmmonProcesses.Count -gt 1) {
  $vmmonProcesses | Stop-Process -Force
  Start-Sleep -Milliseconds 500
  $vmmonProcesses = @()
}
if ($vmmonProcesses.Count -eq 0) {
  Start-Process -FilePath $vmmon -WindowStyle Hidden
  Start-Sleep -Seconds 1
}
$vmmonProcesses = @(Get-Process vmmon64 -ErrorAction SilentlyContinue)
if ($vmmonProcesses.Count -ne 1) {
  throw "Expected exactly one vmmon64.exe after setup; found $($vmmonProcesses.Count)."
}

function Set-ConfigProperty {
  param([object]$Object, [string]$Name, [object]$Value)
  if ($Object.PSObject.Properties.Name -contains $Name) {
    $Object.$Name = $Value
  } else {
    $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value
  }
}

Set-ConfigProperty $config.host "vmrun_path" $vmrun
Set-ConfigProperty $config.host "vmmon64_path" $vmmon
Set-ConfigProperty $config.host "windbg_path" $windbg
Set-ConfigProperty $config.host "msbuild_path" $msbuild
$json = $config | ConvertTo-Json -Depth 20
$encoding = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Resolve-Path -LiteralPath $ConfigPath).Path, $json + "`r`n", $encoding)

$result = [pscustomobject]@{
  ok = $true
  status = "host_ready"
  config_path = (Resolve-Path -LiteralPath $ConfigPath).Path
  vmrun_path = $vmrun
  vmmon64_path = $vmmon
  windbg_path = $windbg
  msbuild_path = $msbuild
  vmmon_pid = $vmmonProcesses[0].Id
  virtualkd_registry_updated = $needsRegistryChange
  next_action = "Run harness_cli.py doctor for the selected target."
} | ConvertTo-Json -Depth 4
if ($ResultPath) {
  [IO.File]::WriteAllText($ResultPath, $result + "`r`n", $encoding)
}
$result
