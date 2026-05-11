---
name: kernel-driver-testing
description: End-to-end Windows kernel driver test automation with VMware, VirtualKD-Redux, WinDbg, and MCP. Use when Codex needs to set up or diagnose the driver harness, deploy a .sys into a VM, load/unload a kernel driver, run a driver test/fix loop, trigger or analyze BSODs, inspect WinDbg output, recover a VM snapshot, or decide which driver-harness-mcp/vmware-mcp/windbg-ext-mcp tools to call instead of writing ad-hoc scripts.
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
                          query_debugger_status, ensure_debugger_ready,
                          recover_to_clean_state, wait_mcp_ready,
                          run_driver_load_verify)
  -> windbg-ext-mcp      (break_in, run_command, run_sequence, !analyze, lm)
  -> vmware-mcp          (snapshot, start, copy files, run guest programs)
```

Never generate a fresh PowerShell/Python orchestration script for the normal
driver load/verify loop. Use `run_driver_load_verify`. Scripts are a fallback
only when the requested workflow is outside the exposed MCP tools.

## Session Start

1. Call `driver-harness-mcp.diagnose_environment(check_guest=false)` before any
   VM or debugger operation.
2. If it reports missing config, help the user create
   `driver-harness.config.json` from `driver-harness.config.example.json`.
3. Do not guess `vm.vmx_path`, `vm.baseline_snapshot`, `guest.admin_user`, or
   `guest.admin_password`. Ask the user or use `${env:VAR}` for secrets.
4. If `vmmon64.exe` is configured but not running, call
   `driver-harness-mcp.start_vkd_monitor`.
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
AI loses MCP control. If registry values change, restart `vmmon64.exe`.

Baseline snapshot contract: the baseline snapshot must already contain the
guest-side debugging setup. The user must boot the guest, enable debug boot,
install/configure VirtualKD-Redux guest support or KDNET, enable testsigning
when needed, install VMware Tools, set a non-empty admin password, reboot, and
only then take the baseline snapshot. Restoring the snapshot should put the VM
back into a state that can immediately enter two-machine kernel debugging once
`vmmon64.exe` is running on the host.

Startup order for VirtualKD automation:

1. Stop `vmmon64.exe` if changing `DebuggerType` or `CustomDebuggerTemplate`.
2. Write `DebuggerType=2` and the MCP `CustomDebuggerTemplate`.
3. Start `vmmon64.exe`.
4. Revert/start the VM. `vmmon64.exe` must already be running so it can observe
   the VirtualKD event and auto-launch WinDbg with MCP.

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
- Do not take the baseline snapshot before guest VirtualKD/KDNET is configured.
- Do not revert/start the VM while `vmmon64.exe` is stopped and expect WinDbg to
  appear automatically.
- Do not change VKD registry values while leaving an old `vmmon64.exe` instance
  running; stop it first, then restart it after the registry write.
- Do not hardcode VM paths, credentials, usernames, or IPs in generated files.
- Do not replace a high-level MCP tool with ad-hoc scripts for the same job.
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
