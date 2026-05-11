# AI Entry Point

This repository is an AI-operated Windows kernel driver harness, not a normal
application repo. Before changing code or running tests, read:

- `skills/kernel-driver-testing/SKILL.md`
- `driver-harness.config.example.json`

Core operating rules:

1. The user must provide a baseline VMware snapshot that already has guest-side
   VirtualKD two-machine kernel debugging configured. A normal Windows snapshot
   is not valid.
2. Before any VM restore/start, make `vmmon64.exe` ready first. It must already
   be running when the VM reaches the VirtualKD debug path, because it observes
   that event and auto-launches WinDbg.
3. If `host.vmmon64_path` is empty, probe common VirtualKD-Redux locations. If
   probing fails, ask the user for the `vmmon64.exe` path and write the
   confirmed value to `driver-harness.config.json`.
4. For a closed loop, ask the user to run the current agent/session as
   Administrator. HKLM registry writes and reliable vmmon restart are elevated
   host operations.
5. Before a VirtualKD snapshot restore, call
   `driver-harness-mcp.start_vkd_monitor`. If it fails because the path is
   unknown, ask the user for `vmmon64.exe`. If it fails because elevation is
   needed, ask the user to rerun the current agent/session as Administrator or
   start vmmon manually.
6. Before a VirtualKD snapshot restore, call
   `driver-harness-mcp.cleanup_windbg_instances(only_harness_mcp=true)`.
   `driver-harness-mcp.recover_to_clean_state` and
   `driver-harness-mcp.run_driver_load_verify` already do this preflight by
   default, so prefer them over raw `vmware-mcp` restore/start calls.
7. After `\\.\pipe\windbgmcp` appears, call
   `driver-harness-mcp.query_debugger_status`.
8. Before guest/vmrun work, call
   `driver-harness-mcp.ensure_debugger_ready(desired_state="running")`.
9. Before WinDbg inspection commands, call
   `driver-harness-mcp.ensure_debugger_ready(desired_state="broken")`.
10. For ordinary driver load/unload tests, prefer
   `driver-harness-mcp.run_driver_load_verify`. Generate scripts when the user
   asks for reusable tests or when the scenario is outside that tool's coverage.
