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
4. Revert or start the VM.

`vmmon64.exe` must be running before the VM reaches the VirtualKD debug path.
If it is stopped, it will not observe the VM event and will not auto-launch
WinDbg. A running monitor may keep using the old launch configuration after a
registry edit, so restart it after every registry change.

Quick verification:

```powershell
powershell -ExecutionPolicy Bypass -File installer\test-vkd-mcp-autostart.ps1 -RequireVmmon
```

Expected high-level result:

- `DebuggerType=2` passes.
- `CustomDebuggerTemplate` contains `windbgmcpExt.dll` and `!mcpstart`.
- The referenced DLL exists.
- `vmmon64.exe` is running after restart.
