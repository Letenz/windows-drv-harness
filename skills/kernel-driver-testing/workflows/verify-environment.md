# Workflow: Verify the Driver Harness Environment

Use this before running driver tests, after setup changes, or when a previous
run failed before the driver code was exercised.

## Preferred Path

1. Call `driver-harness-mcp.diagnose_environment(check_guest=false)`.
2. Confirm the config flags say the baseline snapshot was taken after the user
   completed guest-side VirtualKD two-machine debugging setup. Restoring this
   snapshot must enter a debug-ready guest state once host `vmmon64.exe` is
   running; if not, stop and ask the user to rebuild the baseline. KDNET is
   acceptable only when the VM is explicitly configured for KDNET.
3. Before any VM restore/start, make `vmmon64.exe` ready. If host checks are
   green but `vmmon64.exe running` is false, call
   `driver-harness-mcp.start_vkd_monitor`. If `host.vmmon64_path` is empty,
   probe only config/env/registry/fixed default paths; do not recursively scan
   drives or folders. If probing fails, ask the user for the `vmmon64.exe` path
   and save it in config. Prefer running the current agent elevated/as
   Administrator so it can start/restart `vmmon64.exe` and repair HKLM registry
   settings without handing control back to the user.
4. If you need to prove the guest credentials and snapshot, call
   `driver-harness-mcp.diagnose_environment(check_guest=true)`.
5. Before starting or reverting a VirtualKD guest, call
   `driver-harness-mcp.cleanup_windbg_instances(only_harness_mcp=true)`.
   This closes stale WinDbg instances from previous snapshots so the MCP pipe
   cannot attach to the wrong debugger.
6. If a VM was started/reverted and WinDbg should be available, call
   `driver-harness-mcp.wait_mcp_ready(timeout_seconds=120)`.
7. Call `driver-harness-mcp.query_debugger_status`.
8. If the next step is guest execution, call
   `driver-harness-mcp.ensure_debugger_ready(desired_state="running")`.
   If the next step is WinDbg inspection, call
   `driver-harness-mcp.ensure_debugger_ready(desired_state="broken")`, then
   confirm with `windbg-ext-mcp.run_command(command="vertarget")`.

Before starting `vmmon64`, always check the VirtualKD registry result from
`diagnose_environment`: `DebuggerType` must be `2`, and
`CustomDebuggerTemplate` must contain `windbgmcpExt.dll` and `!mcpstart`.
If `DebuggerType=3` or the template is wrong, stop `vmmon64`, repair the
registry, then start `vmmon64` again. Do not edit the registry and assume an
already-running monitor picked it up.

## How To Read Failures

- Missing `driver-harness.config.json`: create it from the example and ask for
  the four non-guessable values: VMX path, baseline snapshot, guest admin user,
  and guest admin password or env-var reference.
- Missing `vmrun.exe`: use the diagnosed path hint, `VMRUN_PATH`, or
  `host.vmrun_path`. Do not search the whole disk for VMware tools.
- Missing `vmmon64.exe`: ask for the VirtualKD-Redux install folder, then write
  `host.vmmon64_path` after the user confirms the path. The AI can manage
  vmmon once the path is known; admin/elevated agent rights are recommended.
  Do not search whole drives, download folders, or arbitrary tool folders.
- `vmmon64.exe` stopped: start it before reverting/starting the VM. It is the
  host-side monitor that notices the VirtualKD debug event and launches WinDbg.
- Agent not elevated/admin: OK for read-only diagnosis, but not ideal for the
  closed loop. Ask the user to rerun the current agent/session as Administrator
  if registry repair or reliable vmmon restart is needed.
- Access denied while writing VKD registry or starting/stopping vmmon: ask the
  user to rerun the agent as Administrator or perform that single host step in
  an elevated shell.
- Missing `windbgmcp pipe`: the VM, VirtualKD monitor, WinDbg startup command,
  or extension load path is not ready. Do not continue to driver testing.
- Multiple WinDbg instances: close stale harness-owned sessions before
  reverting. Multiple pipe servers can make the AI talk to an old snapshot.
  Prefer `cleanup_windbg_instances`, which asks reachable WinDbg MCP sessions
  to exit themselves before falling back to process termination.
- `query_debugger_status` missing or fails: install the current
  `windbgmcpExt.dll`; older extension builds cannot report target state
  without changing it.
- `DebuggerType=3`: wrong for MCP automation. Set `DebuggerType=2` (Custom),
  keep the MCP `CustomDebuggerTemplate`, then restart `vmmon64.exe`.
- Baseline flags false or unknown: the user must create a baseline snapshot
  after guest VirtualKD two-machine debugging setup. Reverting a normal
  pre-debug Windows snapshot will never produce the WinDbg MCP pipe. KDNET is
  an alternative only when explicitly configured.
- VMware Tools/auth failure: fix guest Tools or credentials and retake the
  baseline snapshot after the fix.

## Stop Conditions

Stop and report the blocker when any required check is red. A custom script
cannot work around a missing VM, missing debug-ready snapshot, missing
credentials, or missing debugger pipe.
