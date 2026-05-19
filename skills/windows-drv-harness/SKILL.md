---
name: windows-drv-harness
description: Operate a Windows kernel driver testing lab with VMware Workstation, VirtualKD-Redux, WinDbg/KD dbgeng, self-developed windbg-mcp, and vmware-mcp. Use when an agent must set up or diagnose the environment, configure VirtualKD autostart, start vmmon64.exe, register MCP servers, deploy a .sys into a VM, load/unload a kernel driver, inspect debugger state, analyze a crash, recover a VMware snapshot, or run a build-test-fix loop.
---

# Windows Driver Harness

This skill is the operating manual. There is no extra high-level harness MCP
server. Use `windbg-mcp` for debugger work, `vmware-mcp` or `vmrun.exe` for
VMware work, and bounded PowerShell for host setup. Keep VirtualKD's automatic
debugger launch disabled; the agent starts classic GUI `windbg.exe` manually
after it sees the VirtualKD KD pipe.

Resolve all relative paths below from the directory containing this `SKILL.md`.
Call that directory `<SKILL_DIR>`.

## Mental Model

```text
agent
  -> <SKILL_DIR>\windbg-mcp\windbg-mcp.exe
       wm_session, wm_run_cmd, wm_wait_event, wm_break_in,
       wm_analyze_crash, wm_exit
  -> <SKILL_DIR>\vmware-mcp or vmrun.exe
       snapshot revert/start, copy files, run guest programs
  -> host PowerShell
       bounded path probing, VirtualKD registry, vmmon64.exe,
       stale KD/WinDbg cleanup
```

Expected loop:

```text
build driver -> restore VirtualKD-ready snapshot -> deploy .sys ->
load service -> collect WinDbg/guest evidence -> unload -> revert ->
patch code -> repeat
```

## Non-Negotiable Rules

- The user must provide a VMware snapshot that is already prepared for
  two-machine kernel debugging. A normal Windows snapshot is not valid.
- For VirtualKD-Redux, `vmmon64.exe` must run before the VM is restored or
  started. vmmon observes the guest debug event and exposes the KD pipe.
- Unless the user explicitly provides a kernel debugger pipe, use the
  VirtualKD main KD pipe exposed by vmmon (`\\.\pipe\kd_*`) as WinDbg's
  `-k com:pipe,port=...` transport. Do not invent a pipe name, use a stale
  saved pipe, or use `\\.\pipe\windbgmcp` as the kernel debugger transport.
- Disable VirtualKD's automatic debugger launch (`AutoInvokeDebugger=0`).
  The agent must launch WinDbg itself after the KD pipe appears. This avoids
  vmmon racing the agent, spawning duplicate WinDbg instances, or relaunching
  stale debuggers after snapshot restore.
- `vmmon64.exe` reads `HKLM\Software\VirtualKD-Redux\Monitor` when it starts.
  If `AutoInvokeDebugger`, `DebuggerType`, or `CustomDebuggerTemplate`
  changes, stop vmmon first, edit the registry, then start vmmon again.
- `vmmon64.exe` should have exactly one running instance. During one-time
  setup or registry changes, stop old vmmon, edit the registry, then start one
  vmmon. During normal test sessions, if the registry is already correct and
  exactly one vmmon is running, reuse it. Do not start another vmmon just to
  be safe.
- Use `DebuggerType=2` (Custom). Do not use `DebuggerType=3`; WinDbg Preview
  mode can ignore `CustomDebuggerTemplate` and start the debugger without
  `mcpext.dll`.
- Use classic GUI `windbg.exe -b -logo <log> -c ".load ...; !mcpext.start; g"
  -k com:pipe,port=<kd pipe>,resets=0,reconnect` when launching manually.
  The `-b` flag is required: without it, WinDbg can attach to the VirtualKD
  pipe but never reach the first prompt, so the `-c` command chain never
  starts and `\\.\pipe\windbgmcp` never appears.
- For visibility, keep the GUI WinDbg window and enable a debugger log with
  `-logo`. Agents should report both the GUI/log path and `windbg-mcp`
  structured state.
- Use a unique WinDbg log path for each launch. A fixed `-logo` file can be
  held open by an elevated stale WinDbg and cause an "in use" dialog.
- When launching WinDbg with PowerShell `Start-Process`, build one quoted
  argument string. Do not pass an `ArgumentList` array for `-c`; semicolons and
  spaces can lose quoting, causing WinDbg to treat the DLL path as a program
  and show Win32 error 2.
- Do not infer debugger state from screenshots, prompts, or window focus. Use
  `windbg-mcp.wm_session`, `windbg-mcp.wm_break_in`, and
  `windbg-mcp.wm_wait_event`.
- If WinDbg starts but `\\.\pipe\windbgmcp` never appears, the environment is
  not ready. Do not send keystrokes, use window titles, press Ctrl+Break, or
  let vmmon relaunch another debugger. Close the stale WinDbg, ensure there is
  exactly one vmmon with autostart disabled, and retry the snapshot sequence
  once.
- `mcpext.dll` accepts one pipe client at a time. Avoid overlapping direct
  `windbg-mcp` calls.
- Do not search whole drives, user profiles, download folders, or arbitrary
  tool directories. Probe only explicit user input, config, environment
  variables, registry values, and fixed default install paths. If bounded
  probing fails, ask the user for the path.
- Never run recursive `Get-ChildItem` from a drive root to discover `.vmx`,
  `vmrun.exe`, `vmmon64.exe`, or WinDbg.
- Do not infer the target VMX. If `vm.vmx_path` is missing, ask the user for
  the VMX path. `vmrun list` is only a verification aid after the user has
  provided or confirmed a VMX; it is not authorization to pick a VM.
- Do not write plaintext passwords to `windows-drv-harness.config.json`. If
  the user gives a password in chat, keep it in memory for the current run or
  ask for an environment variable name.
- Ask the user before registering this skill or MCP servers into the current
  agent/client. Merge with existing config; never overwrite it wholesale.
- Ask the user to run the current agent/session as Administrator for automated
  HKLM writes and reliable vmmon control.

## Bundled Files

```text
SKILL.md
windbg-mcp/mcpext.dll
windbg-mcp/windbg-mcp.exe
windbg-mcp/*.sha256
vmware-mcp/
windows-drv-harness.config.example.json
windows-drv-harness.config.schema.json
```

## One-Time Setup

Work from `<SKILL_DIR>` unless an absolute path is shown.

1. Initialize submodules from the repository root if `vmware-mcp`
   is empty:

```powershell
git submodule update --init --recursive -- .\skills\windows-drv-harness\vmware-mcp
```

2. Install `vmware-mcp`:

```powershell
py -3.11 -m venv .\vmware-mcp\.venv
.\vmware-mcp\.venv\Scripts\python.exe -m pip install -U pip
.\vmware-mcp\.venv\Scripts\python.exe -m pip install -e .\vmware-mcp
```

`windbg-mcp.exe` is native and does not need a Python venv. Keep
`mcpext.dll` beside it and load that bundled DLL directly.

3. Create local config:

```powershell
Copy-Item .\windows-drv-harness.config.example.json .\windows-drv-harness.config.json
```

Optionally verify bundled binary hashes after replacing `windbg-mcp` builds:

```powershell
Get-FileHash .\windbg-mcp\mcpext.dll -Algorithm SHA256
Get-Content .\windbg-mcp\mcpext.dll.sha256
Get-FileHash .\windbg-mcp\windbg-mcp.exe -Algorithm SHA256
Get-Content .\windbg-mcp\windbg-mcp.exe.sha256
```

Fill in:

- `vm.vmx_path`: absolute path to the VMware `.vmx`
- `vm.baseline_snapshot`: VirtualKD-ready baseline snapshot name
- `guest.admin_user` and `guest.admin_password`: prefer `${env:VAR_NAME}`
- `host.vmrun_path`: optional if VMware is in a default location
- `host.vmmon64_path`: path to `vmmon64.exe`; if unknown, bounded-probe first,
  then ask the user
- `flags.baseline_snapshot_created=true` only after the baseline snapshot is
  truly VirtualKD/KDNET ready

4. Configure VirtualKD-Redux registry as Administrator. Stop old vmmon first
   and disable automatic debugger launch:

```powershell
Get-Process vmmon64 -ErrorAction SilentlyContinue | Stop-Process -Force

$debugger = "C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\windbg.exe"
$dll = (Resolve-Path .\windbg-mcp\mcpext.dll).Path
$logDir = Join-Path $env:TEMP "windows-drv-harness"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("windbg-virtualkd-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$template = "`"$debugger`" -logo `"$log`" -b -c `".load $dll; !mcpext.start; g`" -k com:pipe,port=`$(pipename),resets=0,reconnect"

New-Item -Path HKLM:\Software\VirtualKD-Redux\Monitor -Force | Out-Null
Set-ItemProperty -Path HKLM:\Software\VirtualKD-Redux\Monitor -Name DebuggerType -Type DWord -Value 2
Set-ItemProperty -Path HKLM:\Software\VirtualKD-Redux\Monitor -Name AutoInvokeDebugger -Type DWord -Value 0
Set-ItemProperty -Path HKLM:\Software\VirtualKD-Redux\Monitor -Name InitialBreakIn -Type DWord -Value 1
Set-ItemProperty -Path HKLM:\Software\VirtualKD-Redux\Monitor -Name WaitForOS -Type DWord -Value 1
Set-ItemProperty -Path HKLM:\Software\VirtualKD-Redux\Monitor -Name CustomDebuggerTemplate -Type String -Value $template
```

If the agent is not elevated, stop and ask the user to grant admin rights or
perform this step manually.

5. Ensure exactly one `vmmon64.exe` is running before any VM restore/start:

```powershell
$vmmon = "<path from config, env, registry, or explicit user input>"
$running = @(Get-Process vmmon64 -ErrorAction SilentlyContinue)
if ($running.Count -eq 0) {
  Start-Process -FilePath $vmmon -WindowStyle Hidden
} elseif ($running.Count -eq 1) {
  Write-Output "Reusing vmmon64.exe PID $($running[0].Id)"
} else {
  throw "Multiple vmmon64.exe instances are running; stop duplicates before continuing."
}
```

If bounded probing cannot locate `vmmon64.exe`, ask the user for it and write
it to `host.vmmon64_path`.

6. After setup is green, ask the user whether to register this skill and the
MCP servers in the current agent/client.

## MCP Server Registration

Register only after user confirmation. Use absolute paths.

```json
{
  "mcpServers": {
    "windbg-mcp": {
      "command": "<SKILL_DIR>\\windbg-mcp\\windbg-mcp.exe",
      "args": []
    },
    "vmware": {
      "command": "<SKILL_DIR>\\vmware-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "vmware_mcp.server"],
      "env": {
        "VMRUN_PATH": "C:\\Program Files (x86)\\VMware\\VMware Workstation\\vmrun.exe"
      }
    }
  }
}
```

If the client supports per-server working directories, set cwd to
`<SKILL_DIR>\windbg-mcp` for `windbg-mcp` and `<SKILL_DIR>\vmware-mcp` for
`vmware`.

## Bounded Path Probing

Use this order. Do not recurse or scan drives.

- `vmrun.exe`: explicit input, `host.vmrun_path`, `VMRUN_PATH`, VMware
  Workstation registry `InstallPath`, then default install paths.
- `.vmx`: explicit input or `vm.vmx_path` from config only. If missing, ask
  the user. Do not enumerate `*.vmx`. Do not select a VM just because
  `vmrun list` shows one running VM.
- `vmmon64.exe`: explicit input, `host.vmmon64_path`,
  `WINDOWS_DRV_HARNESS_VMMON64`, `VMMON64_PATH`, VirtualKD registry
  `InstallPath`, then `C:\Program Files\VirtualKD-Redux\vmmon64.exe` and
  `C:\Program Files (x86)\VirtualKD-Redux\vmmon64.exe`.
- WinDbg/KD: prefer classic `windbg.exe` from the Windows Kits debugger
  default paths for visible automation. Use `kd.exe` only for headless runs.
  If neither is found, ask the user.

## Session Start Sequence

At the start of every test session, run this as a hard gate. Do not restore,
start, stop, or otherwise touch the VM until every item passes.

1. Read `<SKILL_DIR>\windows-drv-harness.config.json`. If it is missing,
   create it from the example and ask only for missing values. Ask for VMX and
   snapshot names; never discover them by drive scanning or by choosing from
   `vmrun list`.
2. If `guest.admin_password` is missing, ask for a password or env var. If the
   user provides a password directly, keep it in a transient variable and do
   not write it into config.
3. Check that the snapshot flag and debug transport flags match reality. The
   snapshot must already be VirtualKD/KDNET ready.
4. Verify VirtualKD registry and ensure exactly one vmmon in the same preflight.
   Restart vmmon only when the registry must change. The registry must keep
   automatic debugger launch disabled:

```powershell
$skill = "<absolute SKILL_DIR>"
$dll = (Resolve-Path (Join-Path $skill "windbg-mcp\mcpext.dll")).Path
$debugger = "C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\windbg.exe"
$logDir = Join-Path $env:TEMP "windows-drv-harness"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("windbg-virtualkd-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
$template = "`"$debugger`" -logo `"$log`" -b -c `".load $dll; !mcpext.start; g`" -k com:pipe,port=`$(pipename),resets=0,reconnect"

$reg = "HKLM:\Software\VirtualKD-Redux\Monitor"
$v = Get-ItemProperty -Path $reg -ErrorAction SilentlyContinue
$needsFix = $null -eq $v -or
  $v.DebuggerType -ne 2 -or
  $v.AutoInvokeDebugger -ne 0 -or
  [string]::IsNullOrWhiteSpace($v.CustomDebuggerTemplate) -or
  -not $v.CustomDebuggerTemplate.Contains("windbg.exe") -or
  -not $v.CustomDebuggerTemplate.Contains("-logo") -or
  -not $v.CustomDebuggerTemplate.Contains("-b") -or
  -not $v.CustomDebuggerTemplate.Contains($dll) -or
  -not $v.CustomDebuggerTemplate.Contains("!mcpext.start") -or
  -not $v.CustomDebuggerTemplate.Contains("-c") -or
  $v.CustomDebuggerTemplate.Contains("-bonc")

$vmmon = "<path from config, env, registry, default path, or explicit user input>"
$vmmonProcs = @(Get-Process vmmon64 -ErrorAction SilentlyContinue)
if ($vmmonProcs.Count -gt 1) {
  throw "Multiple vmmon64.exe instances are running; stop duplicates before continuing."
}

if ($needsFix) {
  if ($vmmonProcs.Count -eq 1) {
    Stop-Process -Id $vmmonProcs[0].Id -Force -ErrorAction Stop
    Start-Sleep -Seconds 1
  }
  New-Item -Path $reg -Force | Out-Null
  Set-ItemProperty -Path $reg -Name DebuggerType -Type DWord -Value 2
  Set-ItemProperty -Path $reg -Name AutoInvokeDebugger -Type DWord -Value 0
  Set-ItemProperty -Path $reg -Name InitialBreakIn -Type DWord -Value 1
  Set-ItemProperty -Path $reg -Name WaitForOS -Type DWord -Value 1
  Set-ItemProperty -Path $reg -Name CustomDebuggerTemplate -Type String -Value $template
  Start-Process -FilePath $vmmon -WindowStyle Hidden
} elseif ($vmmonProcs.Count -eq 0) {
  Start-Process -FilePath $vmmon -WindowStyle Hidden
} else {
  Write-Output "Reusing vmmon64.exe PID $($vmmonProcs[0].Id)"
}

Start-Sleep -Seconds 1
$running = @(Get-Process vmmon64 -ErrorAction SilentlyContinue)
if ($running.Count -ne 1) {
  throw "Expected exactly one vmmon64.exe instance; found $($running.Count)."
}
Write-Output "Debugger log: $log"
```

5. Close stale harness-owned KD/WinDbg processes before snapshot restore.
   First use `windbg-mcp.wm_exit` if a live pipe is reachable; then kill only
   debugger processes whose command line clearly matches the automation:

```powershell
Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -in @("kd.exe", "cdb.exe", "windbg.exe", "windbgx.exe", "WinDbgX.exe") -and
    ($_.CommandLine -match "mcpext\.dll|windbgmcpExt\.dll|!mcpext\.start|!mcpstart|\\\\\.\\pipe\\windbgmcp|com:pipe")
  } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
```

If a debugger process exists but command line is blank and no
`\\.\pipe\windbgmcp` is live, stop and ask whether to close it. Do not continue
into a restore with ambiguous stale debugger processes.

If `\\.\pipe\windbgmcp` is still live before restore, do not launch a second
debugger. Use `windbg-mcp.wm_exit` first; if it cannot exit WinDbg because of
permissions, stop and ask the user for an elevated cleanup.

6. Record existing VirtualKD main KD pipes before restore. Ignore
   `_virtualkd_svc_` helper pipes; they are not the debugger transport. Unless
   the user explicitly gave a kernel debugger pipe for this run, the target
   WinDbg pipe must come from this VirtualKD main-pipe set:

```powershell
$beforeKdPipes = @([System.IO.Directory]::EnumerateFiles("\\.\pipe\") |
  Where-Object { $_ -match "\\\\\.\\pipe\\kd_" -and $_ -notmatch "_virtualkd_svc_" })
```

7. Restore/start the VM using `vmware-mcp`, or `vmrun.exe` as separate checked
   commands. Do not chain stop/revert/start in one long shell command.

```text
vmware.vmrun_snapshot_revert(vm_id=<vmx_path>, name=<baseline_snapshot>)
vmware.vmrun_start(vm_id=<vmx_path>, gui=false)
```

For raw `vmrun.exe`, prefer:

```powershell
& $vmrun revertToSnapshot $vmx $snapshot
if ($LASTEXITCODE -ne 0) { throw "snapshot revert failed" }
& $vmrun start $vmx nogui
if ($LASTEXITCODE -ne 0) { throw "vm start failed" }
```

8. Wait up to 120 seconds for exactly one new VirtualKD main
   `\\.\pipe\kd_*` pipe. If there are zero, vmmon did not observe the
   VirtualKD guest event. Ignore `_virtualkd_svc_` helper pipes. If there are
   multiple new main KD pipes, ask the user which VirtualKD pipe is the target.
   Do not fall back to any non-VirtualKD or remembered pipe unless the user
   explicitly provided it for this run.

```powershell
$deadline = (Get-Date).AddSeconds(120)
$kdPipe = $null
while ((Get-Date) -lt $deadline) {
  $current = @([System.IO.Directory]::EnumerateFiles("\\.\pipe\") |
    Where-Object { $_ -match "\\\\\.\\pipe\\kd_" -and $_ -notmatch "_virtualkd_svc_" })
  $new = @($current | Where-Object { $beforeKdPipes -notcontains $_ })
  if ($new.Count -eq 1) { $kdPipe = $new[0]; break }
  if ($new.Count -gt 1) { throw "Multiple new KD pipes; ask the user which one to use: $($new -join ', ')" }
  Start-Sleep -Seconds 2
}
if (-not $kdPipe) { throw "No new VirtualKD KD pipe appeared; do not launch WinDbg." }
```

9. Launch WinDbg manually against that KD pipe, then wait up to 120 seconds
   for `\\.\pipe\windbgmcp`:

```powershell
$existingMcpPipe = [System.IO.Directory]::EnumerateFiles("\\.\pipe\") -contains "\\.\pipe\windbgmcp"
if ($existingMcpPipe) {
  throw "windbgmcp pipe already exists before launch; exit the stale debugger first."
}

$busy = @(Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -in @("kd.exe", "cdb.exe", "windbg.exe", "windbgx.exe", "WinDbgX.exe") -and
    $_.CommandLine -and
    $_.CommandLine.Contains($kdPipe)
  })
if ($busy.Count -gt 0) {
  throw "Target KD pipe is already used by debugger PID(s): $($busy.ProcessId -join ', '). Do not launch another WinDbg."
}

$args = '-logo "{0}" -b -c ".load {1}; !mcpext.start; g" -k "com:pipe,port={2},resets=0,reconnect"' -f $log, $dll, $kdPipe
Start-Process -FilePath $debugger -ArgumentList $args

$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
  if ([System.IO.Directory]::EnumerateFiles("\\.\pipe\") -contains "\\.\pipe\windbgmcp") { break }
  Start-Sleep -Seconds 2
}
if (-not ([System.IO.Directory]::EnumerateFiles("\\.\pipe\") -contains "\\.\pipe\windbgmcp")) {
  throw "WinDbg launched but windbgmcp pipe never appeared; close stale WinDbg and retry once."
}
```

10. Call `windbg-mcp.wm_session` until it reports an attached kernel target.
   If a debugger exists but the pipe never appears, stop: WinDbg did not load
   `mcpext.dll` or `!mcpext.start` failed. Close the stale debugger, rerun the
   registry/vmmon preflight, and retry restore/start once.
   To watch debugger text during the run, use the WinDbg window or tail the
   debugger log printed by preflight:

```powershell
Get-Content $log -Wait
```

11. Use `windbg-mcp.wm_run_cmd(cmd="g")` to let the guest run when guest-side
   work is needed. Use `windbg-mcp.wm_break_in()` before inspection commands.

## WinDbg Occupied Dialogs

If WinDbg shows an "in use", "busy", "occupied", or access-denied dialog during
launch, assume a stale debugger still owns either the target `\\.\pipe\kd_*`
transport or the previous log file.

- Do not start another WinDbg.
- Capture `Get-CimInstance Win32_Process` for debugger/vmmon processes and
  list `\\.\pipe\kd_*` plus `\\.\pipe\windbgmcp`.
- Prefer `windbg-mcp.wm_exit` when the MCP pipe is live.
- If the stale debugger is elevated and cannot be killed, stop and ask the
  user for an elevated cleanup or an elevated agent session.
- After cleanup, ensure exactly one `vmmon64.exe` is running, record existing
  KD pipes again, restore the VirtualKD-ready snapshot, wait for one new main
  KD pipe, then launch one WinDbg with a fresh unique log path.

## Normal Driver Load Test

For a typical `.sys` load/unload test:

1. Build the driver with the project's normal build system.
2. Restore/start the VirtualKD-ready snapshot using the session sequence.
3. Wait for VMware Tools:

```text
vmware.vmrun_tools_state(vm_id=<vmx_path>)
```

4. Copy the driver into the guest:

```text
vmware.vmrun_copy_to(
  vm_id=<vmx_path>,
  host_path=<absolute .sys path>,
  guest_path=<guest .sys path>,
  user=<guest admin>,
  password=<guest password>
)
```

5. Create and start the kernel service:

```text
vmware.vmrun_run(vm_id=<vmx_path>, program="C:\\Windows\\System32\\sc.exe",
  args="delete <service>", user=<guest admin>, password=<guest password>)
vmware.vmrun_run(vm_id=<vmx_path>, program="C:\\Windows\\System32\\sc.exe",
  args="create <service> type= kernel start= demand binPath= <guest .sys path>",
  user=<guest admin>, password=<guest password>)
vmware.vmrun_run(vm_id=<vmx_path>, program="C:\\Windows\\System32\\sc.exe",
  args="start <service>", user=<guest admin>, password=<guest password>)
```

6. Break in and collect evidence:

```text
windbg-mcp.wm_break_in()
windbg-mcp.wm_run_cmd(cmd="lm m <service>")
windbg-mcp.wm_run_cmd(cmd=".dbgprint")
windbg-mcp.wm_run_cmd(cmd="k")
```

7. Resume, stop/delete the service, break in again, and verify unload:

```text
windbg-mcp.wm_run_cmd(cmd="g")
vmware.vmrun_run(... sc.exe stop <service> ...)
vmware.vmrun_run(... sc.exe delete <service> ...)
windbg-mcp.wm_break_in()
windbg-mcp.wm_run_cmd(cmd="lm m <service>")
windbg-mcp.wm_run_cmd(cmd=".dbgprint")
```

8. Always revert to the baseline snapshot after the test unless the user asks
   to preserve the live crashed/broken state.

## Crash and Live Debugging

- Use `windbg-mcp.wm_session` as the liveness/state probe.
- Use `windbg-mcp.wm_run_cmd` for `!analyze -v`, `.bugcheck`, `k`, `lm`,
  `.trap`, `.cxr`, and targeted inspection commands.
- Use `windbg-mcp.wm_break_in` before inspection if the target is running.
- Use `windbg-mcp.wm_wait_event` instead of polling for bugcheck, break, or
  breakpoint events.
- Use `windbg-mcp.wm_analyze_crash` for structured BSOD reports.
- Copy crash artifacts out before reverting.

Common bugchecks:

- `0x7E`: unhandled kernel exception; inspect exception code and stack.
- `0x50`: invalid memory access; inspect faulting address and IRQL.
- `0xD1`: driver touched invalid/paged memory at elevated IRQL.
- `0xC4`: Driver Verifier caught a contract violation.
- `0x139`: kernel security check failure, often list/cookie/stack corruption.

## What Not To Do

- Do not restore/start the VM before vmmon is running.
- Do not edit VirtualKD registry while an old vmmon instance remains alive.
- Do not launch `vmmon64.exe` when one instance is already running and the
  VirtualKD registry is already correct.
- Do not continue when multiple `vmmon64.exe` instances are running.
- Do not use WinDbg Preview `DebuggerType=3` for this automation path.
- Do not guess VM paths, snapshot names, guest usernames, passwords, or
  unusual tool paths.
- Do not full-disk scan for tools.
- Do not continue after an environment failure. Diagnose, fix the blocker, then
  retry once.
- Do not silently register MCP servers or skills into the current client.
- Do not hardcode secrets in generated files.
- Do not keep the guest stopped in KD break while running `vmrun` guest
  operations; run `g` before calling guest commands such as `sc.exe`.
- Do not call `.crash` or inspection commands while the target is running;
  break in first.
