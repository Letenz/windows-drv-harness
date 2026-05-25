---
name: windows-drv-harness
description: Operate a Windows kernel driver testing lab with VMware Workstation, VirtualKD-Redux, WinDbg/KD dbgeng, bundled windbg-mcp, and vmware-mcp. Use when an agent must set up or diagnose the lab, configure VirtualKD/vmmon64, register MCP servers, deploy a .sys into a VM, load or unload a kernel driver, inspect debugger state, analyze a crash, recover a VMware snapshot, or run a build-test-fix loop.
---

# Windows Driver Harness

Use this skill as a strict runbook for Windows kernel-driver testing. The
default path is deliberately short for small models: collect required inputs,
pass each gate in order, stop on ambiguity, and report concrete evidence.

Resolve all relative paths from this file's directory. Call it `<SKILL_DIR>`.

## Files

```text
<SKILL_DIR>\windbg-mcp\windbg-mcp.exe
<SKILL_DIR>\windbg-mcp\mcpext.dll
<SKILL_DIR>\vmware-mcp\
<SKILL_DIR>\scripts\detect-mcp.ps1
<SKILL_DIR>\scripts\smoke-mcp-server.py
<SKILL_DIR>\scripts\probe-env.ps1
<SKILL_DIR>\scripts\install-mcp.ps1
<SKILL_DIR>\scripts\register-mcp.ps1
<SKILL_DIR>\scripts\invoke-windbg-mcp.py
<SKILL_DIR>\windows-drv-harness.config.example.json
<SKILL_DIR>\windows-drv-harness.config.schema.json
<SKILL_DIR>\references\detailed-runbook.md
```

Read `references/detailed-runbook.md` only when you need exact PowerShell
snippets, VirtualKD registry details, WinDbg launch recovery, occupied-dialog
handling, or the full original manual.

## Operating Contract

- Treat every VM/debugger action as stateful and potentially destructive.
- Do not touch the VM until the preflight gate passes.
- Do not guess VMX paths, snapshot names, passwords, debugger pipes, or unusual
  tool paths. Ask for missing values after bounded probing fails.
- Do not scan whole drives or recurse through user folders to find tools or
  `.vmx` files.
- Fill `<SKILL_DIR>\windows-drv-harness.config.json` before environment checks.
  Persist the VMX, snapshot, tool paths, guest user, and guest password there
  once the user provides or confirms them.
- Plaintext credentials are allowed in the local gitignored config when the
  user asks for that workflow. Redact secrets in all chat output and never
  commit the config.
- VMX path, baseline snapshot, and guest credentials must come from config or
  explicit user input. If any of these are missing, stop and ask. Do not infer
  them from directory names, snapshot names, `vmrun list`, examples, common
  passwords, or previous runs.
- Treat obvious placeholders or common guesses as unconfirmed values:
  `CHANGE_ME`, `TODO`, `test`, `test_mcp` without user confirmation,
  `123456`, `12345678`, `admin`, `password`, `mypass`, blank strings, and a
  password equal to the username.
- `vmrun checkToolsState` does not validate guest credentials. Only a guest
  operation that requires authentication, such as `fileExistsInGuest`,
  `directoryExistsInGuest`, `copyFileFromHostToGuest`, or
  `runProgramInGuest`, can validate them.
- Do not register MCP servers or edit the current client config without user
  confirmation.
- Run one risky operation at a time and check the result before continuing.
- If a gate fails, diagnose that gate and retry once after a concrete fix.
  Stop and ask the user if the second attempt fails or the state is ambiguous.
- First inspect the MCP tools already exposed by the current agent. If
  `windbg-mcp` and `vmware-mcp` tools are visible, use them directly and skip
  MCP detection/registration scripts.

## Required Inputs

Before any test run, know these values:

```text
vm.vmx_path                  absolute VMware .vmx path, user-provided
vm.baseline_snapshot         VirtualKD-ready snapshot name
guest.admin_user             guest administrator account
guest.admin_password         guest password used by vmrun/vmware-mcp
host.vmrun_path              vmrun.exe path or bounded default/env/registry hit
host.vmmon64_path            vmmon64.exe path or bounded default/env/registry hit
classic windbg.exe path      Windows Kits debugger path
```

If `<SKILL_DIR>\windows-drv-harness.config.json` is missing, copy the example
config first. During environment checks, update the config with every value
that is discovered, provided, or confirmed. Ask only for missing required
values. Treat `guest.admin_user` and `guest.admin_password` as the credentials
for VMware guest operations such as `vmrun copyFileFromHostToGuest` and
`vmrun runProgramInGuest`.

Config values that require explicit user confirmation:

```text
vm.vmx_path
vm.baseline_snapshot
guest.admin_user
guest.admin_password
```

If those fields are empty, placeholder-looking, or only guessed, stop before
any VMware action and ask the user to provide them.

If a VMware guest operation reports `Invalid user name or password for the
guest OS`, mark the guest credentials as invalid for this run, stop, and ask
the user for the correct account/password. Do not try alternate usernames,
common passwords, host usernames, repository history, or environment dumps.

## Tool Roles

- There is no extra high-level harness MCP server.
- Use `windbg-mcp` for debugger state, break-in, commands, events, crash
  analysis, and exit. `mcpext.dll` accepts one pipe client at a time, so avoid
  overlapping direct `windbg-mcp` calls.
- Use `vmware-mcp` when available for VMware operations. Use `vmrun.exe` as a
  fallback with separate checked commands.
- Use bounded PowerShell for host setup: registry checks, process checks,
  named-pipe checks, and fixed-path probing.
- Use the visible classic GUI `windbg.exe`, not WinDbg Preview, for the
  VirtualKD automation path.
- For environment probing, prefer the bundled script:
  `powershell -ExecutionPolicy Bypass -File <SKILL_DIR>\scripts\probe-env.ps1`.
  Use its JSON output instead of hand-writing long PowerShell one-liners.
- If direct MCP tools are unavailable but `\\.\pipe\windbgmcp` exists, use the
  bundled JSON-RPC client instead of generating a throwaway script:
  `py -3 <SKILL_DIR>\scripts\invoke-windbg-mcp.py wm_session`
  or `py -3 <SKILL_DIR>\scripts\invoke-windbg-mcp.py wm_run_cmd "lm m nt"`.

## One-Time Setup

First inspect the tools already available in the current agent runtime. If
`windbg-mcp` and `vmware-mcp` tools are already visible, use them directly.

Only when the expected tools are not visible, run client/config detection:

```powershell
powershell -ExecutionPolicy Bypass -File <SKILL_DIR>\scripts\detect-mcp.ps1
```

For a custom/self-written agent, client registration may not be discoverable.
Use the protocol smoke test as the portable check that each server command can
launch and return `tools/list`:

```powershell
py -3 <SKILL_DIR>\scripts\smoke-mcp-server.py --server windbg
py -3 <SKILL_DIR>\scripts\smoke-mcp-server.py --server vmware
```

If Codex/Claude MCP registration is missing, prepare local MCP tooling. This
initializes the bundled VMware MCP submodule if needed, creates
`<SKILL_DIR>\vmware-mcp\.venv`, installs `vmware-mcp`, and verifies bundled
`windbg-mcp.exe` and `mcpext.dll`. It does not edit MCP lists:

```powershell
powershell -ExecutionPolicy Bypass -File <SKILL_DIR>\scripts\install-mcp.ps1
```

Ask before registering MCP servers in the current client. For Codex, register
only after confirmation:

```powershell
powershell -ExecutionPolicy Bypass -File <SKILL_DIR>\scripts\register-mcp.ps1 -Apply
```

If registration fails or no supported client is found, show the manual commands
from `detect-mcp.ps1`/`register-mcp.ps1` and stop.

## Hard Gates

Pass these gates in order. Do not skip ahead.

1. **MCP Setup Gate**
   First check the MCP tools exposed to this agent. If `windbg-mcp` and
   `vmware-mcp` are callable, skip setup scripts. If not, run
   `scripts\detect-mcp.ps1`. If the servers are not registered, run
   `scripts\install-mcp.ps1`, then ask the user before
   `scripts\register-mcp.ps1 -Apply`. For a custom agent, use
   `scripts\smoke-mcp-server.py` only to validate the server command, provide
   the command/config to the user, and stop until the user confirms their
   agent has registered it.

2. **Config Gate**
   Create or update config first, then confirm required inputs. Fill VMX,
   snapshot, tool paths, guest admin user, and guest admin password into the
   config before probing the debugger/VM state. The baseline snapshot must
   have been saved after the guest booted and classic WinDbg successfully
   attached to the kernel target through VirtualKD/KDNET. A cold/offline
   snapshot that has never reached a verified two-machine debugging state is
   not valid.
   If VMX, snapshot, user, or password is missing or guessed, stop and ask the
   user. Do not auto-fill VMX or snapshot from `vmrun list`, filesystem
   searches, or discovered running VMs.

3. **Tool Gate**
   Confirm `windbg-mcp.exe`, `mcpext.dll`, `vmrun.exe`, `vmmon64.exe`, and
   classic `windbg.exe` exist. Run `scripts\probe-env.ps1` for this check.

4. **VirtualKD Gate**
   Require Administrator rights for automated HKLM edits. Ensure VirtualKD
   automatic debugger launch is disabled:
   `AutoInvokeDebugger=0`, `DebuggerType=2`, and a custom template that loads
   bundled `mcpext.dll` and runs `!mcpext.start`. If this gate needs exact
   registry commands, read `references/detailed-runbook.md`.

5. **vmmon Gate**
   Ensure exactly one `vmmon64.exe` is running before snapshot restore/start.
   Stop/restart vmmon only when the VirtualKD registry was changed. If multiple
   instances are running, stop and ask for cleanup or perform a clear cleanup
   with user/admin permission.

6. **Stale Debugger Gate**
   Close only harness-owned stale `windbg.exe`, `kd.exe`, or `cdb.exe`
   processes whose command line references `mcpext.dll`, `!mcpext.start`,
   `windbgmcp`, or `com:pipe`. If a debugger has a blank command line and may
   be unrelated, stop and ask.

7. **Pipe Baseline Gate**
   Record existing VirtualKD main pipes matching `\\.\pipe\kd_*`, excluding
   `_virtualkd_svc_`. Ignore old or helper pipes.

8. **Restore Gate**
   Restore the baseline snapshot, then start the VM. Check each command result.
   Do not combine stop/revert/start in one long shell command.

9. **KD Pipe Gate**
   Wait up to 120 seconds for exactly one new VirtualKD main
   `\\.\pipe\kd_*` pipe. If none appear, vmmon did not observe the guest debug
   event. If more than one appears, ask the user which pipe is the target.

10. **WinDbg Gate**
   Launch one classic GUI `windbg.exe` against the new KD pipe with:
   `-logo <unique log> -b -c ".load <mcpext.dll>; !mcpext.start; g" -k com:pipe,port=<kd pipe>,resets=0,reconnect`.
   Use a unique log path every time. If using PowerShell `Start-Process`, pass
   one quoted argument string; do not split the `-c` command across an
   `ArgumentList` array. Wait up to 120 seconds for `\\.\pipe\windbgmcp`.

11. **Debugger Session Gate**
    Call `windbg-mcp.wm_session` until it reports an attached kernel target.
    Use `windbg-mcp.wm_run_cmd(cmd="g")` before guest-side VMware operations
    if the target is stopped in the debugger.

## Driver Test Loop

Use this loop for a normal `.sys` load/unload test:

1. Build the driver with the project's normal build system.
2. Pass all hard gates and start from the clean snapshot.
3. Wait for VMware Tools in the guest.
4. Copy the `.sys` to a writable guest path.
5. Run `sc.exe delete <service>` to clear stale service state.
6. Run `sc.exe create <service> type= kernel start= demand binPath= <guest .sys>`.
7. Run `sc.exe start <service>`.
8. If the guest crashes, use the crash path below.
9. If it does not crash, break in and collect:
   `lm m <service>`, `.dbgprint`, and `k`.
10. Resume with `g`, then run `sc.exe stop <service>` and
    `sc.exe delete <service>`.
11. Break in again and verify `lm m <service>` no longer shows the module.
12. Revert to the baseline snapshot unless the user asks to preserve state.

## Crash Path

When the VM bugchecks or breaks unexpectedly:

- Use `windbg-mcp.wm_wait_event` or `wm_session` for state.
- Use `windbg-mcp.wm_analyze_crash` for structured crash evidence.
- Also collect targeted commands as needed: `!analyze -v`, `.bugcheck`, `k`,
  `lm`, `.trap`, `.cxr`.
- Copy any requested crash artifacts out before reverting.
- Patch the smallest driver code area that explains the evidence.
- Rebuild, restore the baseline snapshot, redeploy, and retest.

Common bugchecks:

```text
0x7E  unhandled kernel exception; inspect exception code and stack
0x50  invalid memory access; inspect faulting address and IRQL
0xD1  invalid/paged memory touched at elevated IRQL
0xC4  Driver Verifier contract violation
0x139 list/cookie/stack corruption or kernel security check failure
```

## Bounded Probing

Probe only in this order:

- `vmrun.exe`: explicit input, config, `VMRUN_PATH`, VMware Workstation
  registry `InstallPath`, fixed default install paths.
- `.vmx`: explicit input or config only. Do not enumerate `.vmx` files. Do not
  list VM directories. Do not pick from `vmrun list`, snapshot names, or
  "likely" Windows VMs without explicit user confirmation.
- `vmmon64.exe`: explicit input, config, `WINDOWS_DRV_HARNESS_VMMON64`,
  `VMMON64_PATH`, VirtualKD registry `InstallPath`, fixed default install
  paths.
- `windbg.exe`: Windows Kits debugger default paths. Use `kd.exe` only for
  headless runs the user explicitly accepts.

## Failure Playbook

```text
No new kd_* pipe:
  Do not launch WinDbg. Check vmmon is running before restore, snapshot is
  VirtualKD-ready, and helper _virtualkd_svc_ pipes are ignored.

Multiple new kd_* pipes:
  Ask which pipe is target. Do not choose automatically.

windbgmcp pipe never appears:
  Close stale WinDbg, verify command line has -b, .load mcpext.dll, and
  !mcpext.start, then retry the restore/start/launch sequence once.

WinDbg occupied or log in use:
  Do not launch another debugger. Use a unique log path, close harness-owned
  stale debuggers, and read detailed-runbook.md if exact cleanup is needed.

Guest command hangs:
  Check whether the guest is stopped in KD break. Run debugger command `g`
  before `vmrun` guest operations.
```

## Small-Model Stop Rules

When using a small or fast model, follow these extra stops:

```text
Missing VMX/snapshot/user/password:
  Ask the user. Do not search VM folders, enumerate .vmx files, query snapshots
  across candidate VMs, or try common passwords.

Existing config contains placeholders/common guesses:
  Treat the field as missing. Do not use values such as CHANGE_ME, TODO, test,
  123456, 12345678, admin, password, mypass, or password equal to username
  unless the user explicitly confirms that exact value.

Guest credentials fail:
  Stop and ask the user. Do not brute-force, try host usernames, inspect git
  history for secrets, dump environment variables, or keep retrying passwords.

PowerShell quoting error:
  Stop the hand-written command. Use scripts\probe-env.ps1 or a simple command
  without variables. Do not keep retrying escaped one-liners.

Need MCP setup:
  First inspect this agent's callable MCP tools. If the expected tools are
  visible, do not run setup scripts. If tools are missing, run
  scripts\detect-mcp.ps1, then scripts\install-mcp.ps1 if needed. Register
  with scripts\register-mcp.ps1 -Apply only after user confirmation. For
  custom agents, use scripts\smoke-mcp-server.py to validate MCP protocol
  compatibility, then ask the user to add the printed server command to their
  agent. If registration fails, show manual commands and stop.

Need windbg-mcp from shell:
  Use scripts\invoke-windbg-mcp.py. Do not create call_mcp.py or another
  ad-hoc MCP client in the repository root.

Need detailed-runbook.md:
  Read only the section needed for the current gate. Do not load it just
  because it exists.

Need to choose between multiple VMs or snapshots:
  Ask the user. The agent is not authorized to choose.
```

## Reporting

For every run, report the evidence, not guesses:

```text
config values confirmed, with secrets redacted
vmmon PID and VirtualKD registry status
snapshot restore/start result
new KD pipe name
WinDbg log path
windbg-mcp session state
driver copy/create/start/stop/delete results
WinDbg command outputs or crash summary
final VM state: reverted or intentionally preserved
```
