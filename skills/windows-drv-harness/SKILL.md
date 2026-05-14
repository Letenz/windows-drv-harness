---
name: windows-drv-harness
description: Operate a Windows kernel driver testing lab with VMware Workstation, VirtualKD-Redux, WinDbg, self-developed windbg-mcp, and vmware-mcp. Use when an agent must set up or diagnose the environment, configure VirtualKD autostart, start vmmon64.exe, register MCP servers, deploy a .sys into a VM, load/unload a kernel driver, inspect WinDbg state, analyze a crash, recover a VMware snapshot, or run a build-test-fix loop.
---

# Windows Driver Harness

This skill is the operating manual. There is no extra high-level harness MCP
server. Use `windbg-mcp` for debugger work, `vmware-mcp` or `vmrun.exe` for
VMware work, and bounded PowerShell for host setup.

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
       stale WinDbg cleanup
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
  started. vmmon observes the guest debug event and launches WinDbg.
- `vmmon64.exe` reads `HKLM\Software\VirtualKD-Redux\Monitor` when it starts.
  If `DebuggerType` or `CustomDebuggerTemplate` changes, stop vmmon first,
  edit the registry, then start vmmon again.
- Use `DebuggerType=2` (Custom). Do not use `DebuggerType=3`; WinDbg Preview
  mode can ignore `CustomDebuggerTemplate` and start WinDbg without
  `mcpext.dll`.
- Do not infer debugger state from screenshots, prompts, or window focus. Use
  `windbg-mcp.wm_session`, `windbg-mcp.wm_break_in`, and
  `windbg-mcp.wm_wait_event`.
- `mcpext.dll` accepts one pipe client at a time. Avoid overlapping direct
  `windbg-mcp` calls.
- Do not search whole drives, user profiles, download folders, or arbitrary
  tool directories. Probe only explicit user input, config, environment
  variables, registry values, and fixed default install paths. If bounded
  probing fails, ask the user for the path.
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

4. Configure VirtualKD-Redux registry as Administrator. Stop old vmmon first:

```powershell
Get-Process vmmon64 -ErrorAction SilentlyContinue | Stop-Process -Force

$windbg = "C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\windbg.exe"
$dll = (Resolve-Path .\windbg-mcp\mcpext.dll).Path
$template = "`"$windbg`" -k com:pipe,port=`$(pipename),resets=0,reconnect -c `".load $dll; !mcpext.start; g`""

New-Item -Path HKLM:\Software\VirtualKD-Redux\Monitor -Force | Out-Null
Set-ItemProperty -Path HKLM:\Software\VirtualKD-Redux\Monitor -Name DebuggerType -Type DWord -Value 2
Set-ItemProperty -Path HKLM:\Software\VirtualKD-Redux\Monitor -Name AutoInvokeDebugger -Type DWord -Value 1
Set-ItemProperty -Path HKLM:\Software\VirtualKD-Redux\Monitor -Name InitialBreakIn -Type DWord -Value 1
Set-ItemProperty -Path HKLM:\Software\VirtualKD-Redux\Monitor -Name WaitForOS -Type DWord -Value 1
Set-ItemProperty -Path HKLM:\Software\VirtualKD-Redux\Monitor -Name CustomDebuggerTemplate -Type String -Value $template
```

If the agent is not elevated, stop and ask the user to grant admin rights or
perform this step manually.

5. Start `vmmon64.exe` before any VM restore/start:

```powershell
$vmmon = "<path from config, env, registry, or explicit user input>"
Start-Process -FilePath $vmmon -WindowStyle Hidden
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
- `vmmon64.exe`: explicit input, `host.vmmon64_path`,
  `WINDOWS_DRV_HARNESS_VMMON64`, `VMMON64_PATH`, VirtualKD registry
  `InstallPath`, then `C:\Program Files\VirtualKD-Redux\vmmon64.exe` and
  `C:\Program Files (x86)\VirtualKD-Redux\vmmon64.exe`.
- WinDbg: explicit input, Windows Kits debugger default paths. If not found,
  ask the user.

## Session Start Sequence

At the start of every test session:

1. Read `<SKILL_DIR>\windows-drv-harness.config.json`. If it is missing,
   create it from the example and ask only for missing values.
2. Check that the snapshot flag and debug transport flags match reality. The
   snapshot must already be VirtualKD/KDNET ready.
3. Verify `DebuggerType=2` and that `CustomDebuggerTemplate` contains
   `mcpext.dll`, `!mcpext.start`, and `-c`.
4. Ensure `vmmon64.exe` is running before restore/start.
5. Close stale harness-owned WinDbg windows before snapshot restore. First use
   `windbg-mcp.wm_exit` if a live pipe is reachable; then kill only WinDbg
   processes whose command line clearly matches the automation:

```powershell
Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -in @("windbg.exe", "windbgx.exe", "WinDbgX.exe") -and
    ($_.CommandLine -match "mcpext\.dll|windbgmcpExt\.dll|!mcpext\.start|!mcpstart|\\\\\.\\pipe\\windbgmcp|com:pipe")
  } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
```

6. Restore/start the VM using `vmware-mcp`:

```text
vmware.vmrun_snapshot_revert(vm_id=<vmx_path>, name=<baseline_snapshot>)
vmware.vmrun_start(vm_id=<vmx_path>, gui=false)
```

7. Poll `windbg-mcp.wm_session` until it reports an attached kernel target.
   If the pipe is disconnected, wait briefly and retry; if it never connects,
   report that WinDbg did not load `mcpext.dll`.
8. Use `windbg-mcp.wm_run_cmd(cmd="g")` to let the guest run when guest-side
   work is needed. Use `windbg-mcp.wm_break_in()` before inspection commands.

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
- Do not use WinDbg Preview `DebuggerType=3` for this automation path.
- Do not guess VM paths, snapshot names, guest usernames, passwords, or
  unusual tool paths.
- Do not full-disk scan for tools.
- Do not continue after an environment failure. Diagnose, fix the blocker, then
  retry once.
- Do not silently register MCP servers or skills into the current client.
- Do not hardcode secrets in generated files.
- Do not call `.crash` or inspection commands while the target is running;
  break in first.
