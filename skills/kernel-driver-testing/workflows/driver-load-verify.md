# Workflow: Driver Load/Unload Verification

Use this for the common loop: put a `.sys` into the guest, create/start the
kernel service, verify DbgPrint/module evidence, stop/delete the service, and
return the VM to the baseline snapshot.

## Preferred Tool

Call `driver-harness-mcp.run_driver_load_verify` instead of writing scripts.

Required input:

- `sys_path`: absolute host path to the `.sys`.
- `service_name`: service/module name used by `sc create` and `lm m`.

Optional input:

- `load_marker`: expected DbgPrint text after load. Use `""` to skip marker
  validation.
- `unload_marker`: expected DbgPrint text after unload. Use `""` to skip marker
  validation.
- `config_path`, `vmx_path`, `snapshot_name`, `guest_user`, `guest_password`,
  `vmrun_path`, `vmmon64_path`: pass only when overriding config.
- `close_existing_windbg`: defaults to true. Keep it true for automated
  snapshot loops so stale WinDbg/MCP pipe servers from previous runs are closed
  before VirtualKD starts a fresh debugger.

## Interpretation

- `verdict=PASS`: report that load, marker check, module check, unload, and
  final revert succeeded.
- `failed_stage=validate_inputs`: fix config or paths before touching code.
- `failed_stage=start_vkd_monitor`, `wait_for_pipe`, `vertarget`, or
  `wait_vmtools`: treat as environment, not driver code.
- `failed_stage=sc_query`, `lm_after_load`, or `dbgprint_load_marker`: inspect
  `artifacts.load_driver`, WinDbg output, and driver entry path.
- `failed_stage=dbgprint_unload_marker` or `lm_after_unload`: inspect unload
  routine and service cleanup.

## Fallback Only When Needed

If the high-level tool cannot represent the requested test, use primitives:

1. `recover_to_clean_state`.
2. `driver-harness-mcp.ensure_debugger_ready(desired_state="running")`.
3. `vmware-mcp.vmrun_copy_to`.
4. `windbg-ext-mcp.run_command(command="g", timeout_ms=<run window>)`.
5. `vmware-mcp.vmrun_run` with `args` as a JSON array.
6. `driver-harness-mcp.ensure_debugger_ready(desired_state="broken")`.
7. `windbg-ext-mcp.run_command` for `lm`, `.dbgprint`, `.bugcheck`, or
   `!analyze -v`.
8. Revert before the next attempt.

Do not pass `vmrun_run.args` as one shell string for service creation. Use an
array so `type=`, `start=`, and `binPath=` remain distinct arguments.
