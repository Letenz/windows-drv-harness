# Workflow: Verify the Driver Harness Environment

Use this before running driver tests, after setup changes, or when a previous
run failed before the driver code was exercised.

## Preferred Path

1. Call `driver-harness-mcp.diagnose_environment(check_guest=false)`.
2. Confirm the config flags say the baseline snapshot was taken after guest
   VirtualKD/KDNET setup. Restoring this snapshot must enter a debug-ready
   guest state; if not, stop and ask the user to rebuild the baseline.
3. If host checks are green but `vmmon64.exe running` is false, call
   `driver-harness-mcp.start_vkd_monitor`.
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
  `host.vmrun_path`.
- Missing `vmmon64.exe`: ask for the VirtualKD-Redux install folder, then write
  `host.vmmon64_path` after the user confirms the path.
- `vmmon64.exe` stopped: start it before reverting/starting the VM. It is the
  host-side monitor that notices the VirtualKD debug event and launches WinDbg.
- Missing `windbgmcp pipe`: the VM, VirtualKD monitor, WinDbg startup command,
  or extension load path is not ready. Do not continue to driver testing.
- Multiple WinDbg instances: close stale harness-owned sessions before
  reverting. Multiple pipe servers can make the AI talk to an old snapshot.
- `query_debugger_status` missing or fails: install the current
  `windbgmcpExt.dll`; older extension builds cannot report target state
  without changing it.
- `DebuggerType=3`: wrong for MCP automation. Set `DebuggerType=2` (Custom),
  keep the MCP `CustomDebuggerTemplate`, then restart `vmmon64.exe`.
- Baseline flags false or unknown: the user must create a baseline snapshot
  after guest VirtualKD/KDNET setup. Reverting a pre-debug snapshot will never
  produce the WinDbg MCP pipe.
- VMware Tools/auth failure: fix guest Tools or credentials and retake the
  baseline snapshot after the fix.

## Stop Conditions

Stop and report the blocker when any required check is red. Do not generate a
custom orchestration script to work around a missing VM, missing snapshot,
missing credentials, or missing debugger pipe.
