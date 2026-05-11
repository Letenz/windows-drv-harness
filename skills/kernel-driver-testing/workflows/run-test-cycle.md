# Workflow: Run a Driver Test Cycle

This legacy workflow is kept for compatibility. For a normal `.sys`
load/unload test, use [`driver-load-verify.md`](./driver-load-verify.md) and
call `driver-harness-mcp.run_driver_load_verify`.

## Default Path

1. Verify prerequisites with
   [`verify-environment.md`](./verify-environment.md).
2. Call `driver-harness-mcp.run_driver_load_verify`.
3. Use `verdict`, `failed_stage`, and `artifacts` to decide whether the next
   action is environment repair, driver code repair, or crash analysis.

## Custom Path

Only use raw primitives when the requested scenario is not a simple load/unload
test:

1. `driver-harness-mcp.recover_to_clean_state`.
2. `vmware-mcp.vmrun_copy_to` for drivers, test EXEs, configs, or symbols.
3. `windbg-ext-mcp.run_command(command="g", timeout_ms=<run window>)` while the
   guest must run.
4. `vmware-mcp.vmrun_run` using a JSON array for `args`.
5. `windbg-ext-mcp.break_in` before inspection.
6. `windbg-ext-mcp.run_command` for `lm`, `.dbgprint`, `.bugcheck`,
   `!analyze -v`, stack, registers, or memory inspection.
7. Revert before the next iteration unless the user explicitly wants to keep
   the live debug state.

Every cycle should start and end at the baseline snapshot.
