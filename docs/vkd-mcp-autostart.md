# VirtualKD vmmon64 MCP Autostart Checklist

This harness depends on `vmmon64.exe` auto-starting WinDbg with the MCP
extension already loaded. The important detail is that `vmmon64.exe` reads
`HKLM\Software\VirtualKD-Redux\Monitor` when it starts.

The VM baseline snapshot is part of this contract. It must already contain the
guest-side VirtualKD-Redux or KDNET setup: debug boot enabled, guest debug
transport installed/configured, VMware Tools installed, and a non-empty admin
password. Restoring the snapshot should put the guest back into a state that
can immediately enter two-machine kernel debugging.

Required registry state:

- `DebuggerType = 2`
- `AutoInvokeDebugger = 1`
- `CustomDebuggerTemplate` launches WinDbg with:
  - `-k com:pipe,port=$(pipename),resets=0,reconnect`
  - `-c ".load <path>\windbgmcpExt.dll; !mcpstart; ...; g"`

Do not use `DebuggerType=3` for MCP automation. That mode can start WinDbg
without honoring the custom `-c` command, so WinDbg comes up without
`windbgmcpExt.dll`, `!mcpstart` never runs, and `\\.\pipe\windbgmcp` is absent.

Startup order matters:

1. Stop `vmmon64.exe` before changing `DebuggerType` or
   `CustomDebuggerTemplate`.
2. Write the registry values.
3. Start `vmmon64.exe`.
4. Close stale WinDbg instances from previous harness runs.
5. Revert or start the VM.
6. After `\\.\pipe\windbgmcp` appears, query debugger state with
   `driver-harness-mcp.query_debugger_status`.

`vmmon64.exe` must be running before the VM reaches the VirtualKD debug path.
If it is stopped, it will not observe the VM event and will not auto-launch
WinDbg. A running monitor may keep using the old launch configuration after a
registry edit, so restart it after every registry change.

VirtualKD normally starts a new WinDbg for every restored debug snapshot, but
the old WinDbg process may stay open. Those stale processes can keep reconnect
state or create additional `\\.\pipe\windbgmcp` pipe servers, so an AI client
may talk to the wrong debugger. For automation, run
`driver-harness-mcp.cleanup_windbg_instances(only_harness_mcp=true)` before
the snapshot restore. The tool only targets WinDbg processes that look like
harness/VirtualKD sessions, such as command lines containing `windbgmcpExt.dll`,
`!mcpstart`, or `com:pipe`.

Do not infer the target state from the WinDbg prompt. A fresh WinDbg can stop
at `kd>` or continue with `g` depending on timing and startup commands. Use:

- `driver-harness-mcp.ensure_debugger_ready(desired_state="running")` before
  guest-side `vmrun` work.
- `driver-harness-mcp.ensure_debugger_ready(desired_state="broken")` before
  WinDbg inspection commands.

Quick verification:

```powershell
powershell -ExecutionPolicy Bypass -File installer\test-vkd-mcp-autostart.ps1 -RequireVmmon
```

Expected high-level result:

- `DebuggerType=2` passes.
- `CustomDebuggerTemplate` contains `windbgmcpExt.dll` and `!mcpstart`.
- The referenced DLL exists.
- `vmmon64.exe` is running after restart.

After a VM restore has launched WinDbg and `\\.\pipe\windbgmcp` exists, verify
the machine-readable debugger state handler:

```powershell
powershell -ExecutionPolicy Bypass -File installer\test-windbg-debugger-status.ps1
```
