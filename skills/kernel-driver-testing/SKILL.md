---
name: kernel-driver-testing
description: End-to-end Windows kernel driver test automation with VMware, VirtualKD-Redux, WinDbg, and MCP. Use when Codex needs to set up or diagnose the driver harness, deploy a .sys into a VM, load/unload a kernel driver, run a driver test/fix loop, trigger or analyze BSODs, inspect WinDbg output, recover a VM snapshot, or decide which driver-harness-mcp/vmware-mcp/windbg-ext-mcp tools to call.
---

# Kernel Driver Testing

Use the skill as an operating manual for the harness. The core rule is simple:
prefer `driver-harness-mcp` high-level tools first, then fall back to
`windbg-ext-mcp` or `vmware-mcp` primitives only for work the high-level tool
does not cover.

## Tool Layers

```
You
  -> driver-harness-mcp  (diagnose_environment, start_vkd_monitor,
                          list_windbg_processes, cleanup_windbg_instances,
                          exit_windbg, query_debugger_status,
                          ensure_debugger_ready,
                          recover_to_clean_state, wait_mcp_ready,
                          run_driver_load_verify)
  -> windbg-ext-mcp      (break_in, exit_windbg, run_command, run_sequence,
                          !analyze, lm)
  -> vmware-mcp          (snapshot, start, copy files, run guest programs)
```

For the normal driver load/verify loop, prefer `run_driver_load_verify`.
Generate or edit scripts when the user asks for them, when making reusable test
artifacts, or when the requested workflow is outside the exposed MCP tools.

## Session Start

1. Call `driver-harness-mcp.diagnose_environment(check_guest=false)` before any
   VM or debugger operation.
2. If it reports missing config, help the user create
   `driver-harness.config.json` from `driver-harness.config.example.json`.
3. Do not guess `vm.vmx_path`, `vm.baseline_snapshot`, `guest.admin_user`, or
   `guest.admin_password`. Ask the user or use `${env:VAR}` for secrets.
4. Before any VirtualKD VM restore/start, ensure `vmmon64.exe` is already
   running. If it is configured but stopped, call
   `driver-harness-mcp.start_vkd_monitor`. If `host.vmmon64_path` is empty,
   probe only explicit inputs, environment variables, registry values, and fixed
   default install paths. Do not run recursive or drive-wide filesystem
   searches. If probing fails, ask the user for the `vmmon64.exe` path and
   write it into `driver-harness.config.json`.
   For fully automated registry/vmmon management, tell the user the current
   agent should run elevated/as Administrator. If the agent is not elevated and
   vmmon cannot be controlled, ask the user to start `vmmon64.exe` manually or
   rerun the current agent/session as admin.
5. Before reverting/starting a VirtualKD guest, close stale harness-owned
   WinDbg sessions with `driver-harness-mcp.cleanup_windbg_instances`.
   Multiple old WinDbg processes can leave multiple `windbgmcp` pipe servers,
   so the AI may connect to yesterday's debugger instead of the new snapshot.
6. When host prerequisites are green and the VM is expected to be running, call
   `driver-harness-mcp.wait_mcp_ready`, then call
   `driver-harness-mcp.query_debugger_status`.
7. Normalize the debugger state for the next step:
   - Before guest/vmrun work, call
     `driver-harness-mcp.ensure_debugger_ready(desired_state="running")`.
   - Before WinDbg inspection commands such as `vertarget`, `lm`, `k`,
     `.bugcheck`, or `.crash`, call
     `driver-harness-mcp.ensure_debugger_ready(desired_state="broken")`.

Use `diagnose_environment(check_guest=true)` when you need snapshot existence,
VMware Tools, or guest credential checks. It is read-only.

Critical VirtualKD rule: `vmmon64.exe` reads
`HKLM\Software\VirtualKD-Redux\Monitor` at launch and uses that registry state
to auto-start WinDbg. `DebuggerType` must be `2` (Custom) before `vmmon64.exe`
is launched or relaunched. `DebuggerType=3` (WinDbg Preview mode) can ignore
`CustomDebuggerTemplate`, so WinDbg starts without `windbgmcpExt.dll` and the
AI loses MCP control. If registry values change, restart `vmmon64.exe`. Writing
HKLM and reliably controlling `vmmon64.exe` are admin/elevated operations; if
the current agent lacks admin rights, stop and ask the user to grant elevation
or perform that host step manually.

Baseline snapshot contract: the user must provide a VM snapshot that already
has two-machine kernel debugging configured. The default supported path is
VirtualKD-Redux: the guest-side VirtualKD target must be installed/configured,
debug boot must be enabled, VMware Tools must work, testsigning must be enabled
when needed, and the guest admin account must have a non-empty password. Only
after that setup is confirmed should the user take the baseline snapshot.
Restoring this snapshot, with host `vmmon64.exe` already running, should
immediately put the guest on the VirtualKD debug path and let `vmmon64.exe`
auto-launch the MCP-enabled WinDbg. KDNET is an explicit alternative only when
the config/docs say this VM uses KDNET.

Startup order for VirtualKD automation:

1. Stop `vmmon64.exe` if changing `DebuggerType` or `CustomDebuggerTemplate`.
2. Write `DebuggerType=2` and the MCP `CustomDebuggerTemplate`.
3. Start `vmmon64.exe`.
4. Revert/start the VM. `vmmon64.exe` must already be running so it can observe
   the VirtualKD event and auto-launch WinDbg with MCP.

`driver-harness-mcp.recover_to_clean_state` and
`driver-harness-mcp.run_driver_load_verify` perform the vmmon preflight by
default. Prefer them over raw `vmware-mcp` snapshot/start calls unless the user
explicitly asks for primitive control.

## Standard Workflows

- Environment setup and diagnosis: read
  [`workflows/verify-environment.md`](./workflows/verify-environment.md).
- Normal driver load/unload verification: read
  [`workflows/driver-load-verify.md`](./workflows/driver-load-verify.md).
- Iterative build/test/fix loop: read [`workflows/fix-loop.md`](./workflows/fix-loop.md).
- Fresh install walkthrough: read
  [`workflows/setup-from-scratch.md`](./workflows/setup-from-scratch.md).
- Crash triage: read [`workflows/crash-analysis.md`](./workflows/crash-analysis.md).

## Driver Load Tests

For a `.sys` load/unload test, call:

```text
driver-harness-mcp.run_driver_load_verify(
  sys_path=<absolute host path>,
  service_name=<driver service/module name>,
  load_marker=<expected DbgPrint marker or "">,
  unload_marker=<expected DbgPrint marker or "">
)
```

Interpret the returned JSON:

- `verdict=PASS`: report the service name, guest staging path, and key evidence.
- `verdict=FAIL`: use `failed_stage`, `message`, `detail`, and `artifacts` to
  decide the next code change. Do not rerun blindly.
- The tool reverts the VM by default. Keep `always_revert=true` unless the user
  explicitly wants to preserve the crashed/broken state for live investigation.

## Primitive Tool Rules

Use lower-level tools with these guardrails:

- Do not infer WinDbg state from screenshots or prompt text. Use
  `driver-harness-mcp.query_debugger_status`; if the status handler is
  missing, install the current `windbgmcpExt.dll`.
- Prefer `driver-harness-mcp.cleanup_windbg_instances` or
  `driver-harness-mcp.exit_windbg` over external `taskkill` when MCP is still
  reachable. The extension can close its own elevated WinDbg process even when
  the current agent lacks process termination rights.
- Before inspection commands after `g`, call `windbg-ext-mcp.break_in`.
- For long-running `g`, pass `timeout_ms` intentionally; it is the run window.
- For `vmware-mcp.vmrun_run`, pass `args` as a JSON array, not a shell string.
  Example: `["create", "MyDrv", "type=", "kernel", "start=", "demand",
  "binPath=", "C:\\Users\\Administrator\\Desktop\\MyDrv.sys"]`.
- Always copy crash artifacts out of the guest before reverting.
- Always revert after BSOD testing unless the user explicitly asks to keep the
  live debugging state.

## What Not To Do

- Do not `.crash` while the target is running. `break_in` first.
- Do not start `vmmon64.exe` until `DebuggerType=2` and
  `CustomDebuggerTemplate` contains `windbgmcpExt.dll` and `!mcpstart`.
- Do not guess `vmmon64.exe` when probing fails. Ask the user for the path and
  store it in `host.vmmon64_path`.
- Do not search whole drives, user profiles, download folders, or arbitrary
  tool directories for missing host tools. Use config/env/registry/default paths
  only, then ask the user.
- Do not silently continue if HKLM/vmmon control needs admin rights and the
  current agent is not elevated.
- Do not register MCP servers or copy/install skills into the current
  agent/client until the user explicitly confirms.
- Do not treat a normal Windows snapshot as valid. The baseline must be taken
  after guest VirtualKD two-machine debugging is configured and confirmed.
- Do not revert/start the VM while `vmmon64.exe` is stopped and expect WinDbg to
  appear automatically.
- Do not use raw `vmware-mcp` restore/start calls before `start_vkd_monitor`
  succeeds or the user confirms vmmon is already running.
- Do not change VKD registry values while leaving an old `vmmon64.exe` instance
  running; stop it first, then restart it after the registry write.
- Do not hardcode VM paths, credentials, usernames, or IPs in generated files.
- Do not keep retrying after an environment failure. Diagnose, fix the blocker,
  then retry once.
- Do not perform destructive actions such as snapshot revert, VM reset, kernel
  patching, or intentional BSOD unless the config has a valid VMX, baseline
  snapshot, and guest credentials.

## Useful References

- WinDbg command reminders:
  [`knowledge/windbg-cheatsheet.md`](./knowledge/windbg-cheatsheet.md)
- BugCheck lookup:
  [`knowledge/common-bugcheck-codes.md`](./knowledge/common-bugcheck-codes.md)
- VirtualKD details:
  [`knowledge/vkd-debugger-types.md`](./knowledge/vkd-debugger-types.md)
- Troubleshooting table:
  [`docs/troubleshooting.md`](../../docs/troubleshooting.md)
