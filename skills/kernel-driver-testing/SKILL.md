---
name: kernel-driver-testing
description: Operate a Windows kernel driver test harness with VMware Workstation, VirtualKD-Redux, WinDbg, self-developed windbg-mcp, vmware-mcp, and driver-harness-mcp. Use when an agent must set up or diagnose the harness, configure VirtualKD autostart, start vmmon64.exe, register or use the MCP servers, deploy a .sys into a VM, load/unload a kernel driver, run a build-test-fix loop, inspect WinDbg state, analyze a crash, or recover a VMware snapshot.
---

# Kernel Driver Testing

This skill is the canonical operating manual. Do not look for extra project
docs or installer scripts. Prefer `driver-harness-mcp` high-level tools for
the driver test loop; use `windbg-mcp` and `vmware-mcp` directly only when the
harness tool does not cover the requested operation.

## Mental Model

```text
agent
  -> driver-harness-mcp
       diagnose_environment, start_vkd_monitor, cleanup_windbg_instances,
       exit_windbg, query_debugger_status, ensure_debugger_ready,
       recover_to_clean_state, wait_mcp_ready, run_driver_load_verify
  -> windbg-mcp.exe
       wm_session, wm_run_cmd, wm_wait_event, wm_break_in,
       wm_analyze_crash, wm_exit
  -> vmware-mcp
       snapshot, start, copy files, run guest programs
  -> host tools
       vmrun.exe, vmmon64.exe, WinDbg, mcpext.dll
```

The expected loop is:

```text
build driver -> recover VM snapshot -> deploy .sys -> load service ->
collect WinDbg/guest evidence -> unload -> revert -> patch code -> repeat
```

## Non-Negotiable Rules

- The user must provide a VMware snapshot that is already prepared for
  two-machine kernel debugging. A normal Windows snapshot is not valid.
- For VirtualKD-Redux, `vmmon64.exe` must already be running before the VM is
  restored or started. vmmon observes the guest debug event and launches WinDbg.
- `vmmon64.exe` reads `HKLM\Software\VirtualKD-Redux\Monitor` when it starts.
  If `DebuggerType` or `CustomDebuggerTemplate` changes, stop vmmon first,
  edit the registry, then start vmmon again.
- Use `DebuggerType=2` (Custom). Do not use `DebuggerType=3` for automation;
  WinDbg Preview mode can ignore `CustomDebuggerTemplate` and start WinDbg
  without `mcpext.dll`.
- Do not infer debugger state from screenshots, prompts, or window focus. Use
  `query_debugger_status`, `ensure_debugger_ready`, or `wm_session`.
- `mcpext.dll` accepts one pipe client at a time. Do not call direct
  `windbg-mcp` tools while a `driver-harness-mcp` high-level operation is
  running; let the high-level call finish and close its pipe first.
- Do not search whole drives, user profiles, download folders, or arbitrary
  tool directories. Probe only explicit user input, `driver-harness.config.json`,
  environment variables, registry values, and fixed default install paths. If
  bounded probing fails, ask the user for the path.
- Ask the user before registering skills or MCP servers into the current agent
  or client. Merge with existing config; never overwrite it wholesale.
- Ask the user to run the current agent/session as Administrator for a fully
  automated setup. HKLM writes and reliable vmmon control are elevated host
  operations.

## Minimal Repository Layout

Only these repository areas matter:

```text
skills/kernel-driver-testing/SKILL.md     this file
driver-harness-mcp/                       high-level MCP server
third_party/vmware-mcp/                   VMware MCP submodule
bin/mcpext.dll                            self-developed WinDbg extension
bin/windbg-mcp.exe                        self-developed WinDbg MCP server
driver-harness.config.example.json        copy to driver-harness.config.json
driver-harness.config.schema.json         config schema
README.md                                 human-facing overview and prompt examples
```

## One-Time Environment Setup

Work from the repository root. If a command fails because Python is missing,
ask the user to install Python 3.11+ and rerun the current agent/session.

1. Initialize submodules if needed:

```powershell
git submodule update --init --recursive
```

2. Create Python environments for `driver-harness-mcp` and `vmware-mcp`:

```powershell
py -3.11 -m venv driver-harness-mcp\.venv
.\driver-harness-mcp\.venv\Scripts\python.exe -m pip install -U pip
.\driver-harness-mcp\.venv\Scripts\python.exe -m pip install -e .\driver-harness-mcp

py -3.11 -m venv third_party\vmware-mcp\.venv
.\third_party\vmware-mcp\.venv\Scripts\python.exe -m pip install -U pip
.\third_party\vmware-mcp\.venv\Scripts\python.exe -m pip install -e .\third_party\vmware-mcp
```

`windbg-mcp.exe` is a native stdio MCP server and does not need a Python venv.

3. Copy the self-developed WinDbg binaries to the stable ProgramData path:

```powershell
New-Item -ItemType Directory -Force C:\ProgramData\driver-harness-mcp\bin | Out-Null
Copy-Item .\bin\mcpext.dll C:\ProgramData\driver-harness-mcp\bin\mcpext.dll -Force
Copy-Item .\bin\windbg-mcp.exe C:\ProgramData\driver-harness-mcp\bin\windbg-mcp.exe -Force
Get-FileHash C:\ProgramData\driver-harness-mcp\bin\mcpext.dll -Algorithm SHA256
Get-FileHash C:\ProgramData\driver-harness-mcp\bin\windbg-mcp.exe -Algorithm SHA256
Get-Content .\bin\mcpext.dll.sha256
Get-Content .\bin\windbg-mcp.exe.sha256
```

4. Create the user config:

```powershell
Copy-Item .\driver-harness.config.example.json .\driver-harness.config.json
```

Fill in:

- `vm.vmx_path`: absolute path to the VMware `.vmx`
- `vm.baseline_snapshot`: VirtualKD-ready baseline snapshot name
- `guest.admin_user` and `guest.admin_password`: prefer `${env:VAR_NAME}` for
  the password
- `host.vmrun_path`: optional if VMware is in a default location
- `host.vmmon64_path`: path to `vmmon64.exe`; if unknown, bounded-probe first,
  then ask the user
- `flags.baseline_snapshot_created=true` only after the baseline snapshot is
  truly VirtualKD/KDNET ready

5. Configure VirtualKD-Redux registry as Administrator. Stop old vmmon first:

```powershell
Get-Process vmmon64 -ErrorAction SilentlyContinue | Stop-Process -Force

$windbg = "C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\windbg.exe"
$dll = "C:\ProgramData\driver-harness-mcp\bin\mcpext.dll"
$template = "`"$windbg`" -k com:pipe,port=`$(pipename),resets=0,reconnect -c `".load $dll; !mcpext.start; g`""

New-Item -Path HKLM:\Software\VirtualKD-Redux\Monitor -Force | Out-Null
Set-ItemProperty -Path HKLM:\Software\VirtualKD-Redux\Monitor -Name DebuggerType -Type DWord -Value 2
Set-ItemProperty -Path HKLM:\Software\VirtualKD-Redux\Monitor -Name AutoInvokeDebugger -Type DWord -Value 1
Set-ItemProperty -Path HKLM:\Software\VirtualKD-Redux\Monitor -Name InitialBreakIn -Type DWord -Value 1
Set-ItemProperty -Path HKLM:\Software\VirtualKD-Redux\Monitor -Name WaitForOS -Type DWord -Value 1
Set-ItemProperty -Path HKLM:\Software\VirtualKD-Redux\Monitor -Name CustomDebuggerTemplate -Type String -Value $template
```

If the agent is not elevated, do not fake success. Ask the user to grant admin
rights or perform this host step manually.

6. Start `vmmon64.exe` before any VM restore/start. Prefer the MCP tool:

```text
driver-harness-mcp.start_vkd_monitor()
```

If that cannot locate `vmmon64.exe`, ask the user for the path and write it to
`host.vmmon64_path`.

7. After setup and validation are green, ask the user whether to register this
skill and the MCP servers in the current agent/client.

## MCP Server Registration

Register only after user confirmation. Use absolute paths and merge into the
client's existing MCP config.

```json
{
  "mcpServers": {
    "driver-harness": {
      "command": "<REPO_ROOT>\\driver-harness-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "driver_harness_mcp.server"]
    },
    "windbg-mcp": {
      "command": "<REPO_ROOT>\\bin\\windbg-mcp.exe",
      "args": []
    },
    "vmware": {
      "command": "<REPO_ROOT>\\third_party\\vmware-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "vmware_mcp.server"],
      "env": {
        "VMRUN_PATH": "C:\\Program Files (x86)\\VMware\\VMware Workstation\\vmrun.exe"
      }
    }
  }
}
```

If the client supports per-server working directories, set cwd to the repo root.

## Required Session Start Sequence

At the start of every test session:

1. Call:

```text
driver-harness-mcp.diagnose_environment(check_guest=false)
```

2. Fix blockers in order. If config is missing, create it from
   `driver-harness.config.example.json`. If a path is missing, bounded-probe,
   then ask the user.

3. Ensure vmmon is running:

```text
driver-harness-mcp.start_vkd_monitor()
```

4. Close stale harness-owned WinDbg sessions before snapshot restore:

```text
driver-harness-mcp.cleanup_windbg_instances(only_harness_mcp=true)
```

This first tries the reachable WinDbg MCP session's `exit` operation, then
falls back to host-side process termination for remaining stale WinDbg windows.

5. Recover the VM:

```text
driver-harness-mcp.recover_to_clean_state()
```

6. Wait for MCP and query state:

```text
driver-harness-mcp.wait_mcp_ready()
driver-harness-mcp.query_debugger_status()
```

7. Normalize state for the next operation:

```text
driver-harness-mcp.ensure_debugger_ready(desired_state="running")
driver-harness-mcp.ensure_debugger_ready(desired_state="broken")
```

Use `running` before guest/vmrun work. Use `broken` before WinDbg inspection
commands such as `lm`, `k`, `.bugcheck`, `.dbgprint`, or `!analyze -v`.

## Normal Driver Load Test

For an ordinary `.sys` load/unload verification, call:

```text
driver-harness-mcp.run_driver_load_verify(
  sys_path=<absolute host path to .sys>,
  service_name=<driver service/module name>,
  load_marker=<expected DbgPrint marker or "">,
  unload_marker=<expected DbgPrint marker or "">
)
```

Interpret the returned JSON:

- `verdict=PASS`: report service name, guest path, and key evidence.
- `verdict=FAIL`: use `failed_stage`, `message`, `detail`, and `artifacts` to
  choose the next code change. Do not rerun blindly.
- Keep `always_revert=true` unless the user explicitly wants to preserve a
  crashed or broken state.

## Build-Test-Fix Loop

1. Build the driver with the project's normal build system.
2. Run `run_driver_load_verify` against the produced `.sys`.
3. If it fails, inspect the stage-specific evidence:
   - `start_vkd_monitor`: host registry, vmmon path, or admin issue
   - `wait_for_pipe`: VM did not enter the VirtualKD path or WinDbg did not load MCP
   - `sc_query` or `sc_start`: service creation/load failure
   - `dbgprint_*`: driver loaded but expected marker did not appear
   - `lm_*`: module visibility/unload issue
4. Patch the smallest relevant code area.
5. Rebuild and rerun once. If the second run fails with a different environment
   blocker, stop and report the blocker.

## Crash and Live Debugging

- Before crash analysis, call `ensure_debugger_ready(desired_state="broken")`.
- Use `windbg-mcp.wm_session` as a liveness/state probe.
- Use `windbg-mcp.wm_run_cmd` for `!analyze -v`, `.bugcheck`, `k`, `lm`,
  `.trap`, `.cxr`, and targeted inspection commands.
- Use `windbg-mcp.wm_break_in` or
  `driver-harness-mcp.ensure_debugger_ready(desired_state="broken")` before
  inspection if the target is running.
- Use `windbg-mcp.wm_wait_event` instead of polling for bugcheck, break, or
  breakpoint events.
- Use `windbg-mcp.wm_analyze_crash` for structured BSOD reports.
- Copy crash artifacts out before reverting.
- Revert after BSOD testing unless the user explicitly asks to keep the live
  debug state.

Common bugcheck reminders:

- `0x7E`: unhandled kernel exception; inspect exception code and stack.
- `0x50`: invalid memory access; inspect faulting address and IRQL.
- `0xD1`: driver touched invalid/paged memory at elevated IRQL.
- `0xC4`: Driver Verifier caught a contract violation.
- `0x139`: kernel security check failure, often list/cookie/stack corruption.

## WinDbg Process Hygiene

VirtualKD can start a new WinDbg every time the snapshot boots while older
WinDbg windows remain alive. Multiple pipe servers can make the agent talk to
an old snapshot. Before every restore:

```text
driver-harness-mcp.cleanup_windbg_instances(only_harness_mcp=true)
```

If a specific live WinDbg MCP session should be detached:

```text
driver-harness-mcp.exit_windbg(dry_run=true)
driver-harness-mcp.exit_windbg(dry_run=false)
```

The self-developed `wm_exit` operation detaches the dbgeng session. If the
WinDbg UI remains alive after MCP exit, `cleanup_windbg_instances` falls back
to host-side process termination.

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
