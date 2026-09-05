# Windows Driver Harness v2: Manual Recovery

Read only the section needed for a failed high-level tool. The implementation
in `scripts/harness_core.py` is authoritative for normal operation.

## Runtime Layout

```text
%LOCALAPPDATA%\windows-drv-harness\
  config.json
  locks\vm-start.lock
  logs\<target>-<timestamp>.log
  state\<target>.json
```

The skill directory contains executable code and bundled binaries only. A
skill update must not overwrite machine config or runtime state.

Config precedence:

1. Explicit CLI `--config`
2. `WINDOWS_DRV_HARNESS_CONFIG`
3. `%LOCALAPPDATA%\windows-drv-harness\config.json`

Legacy single-VM configs are converted in memory to one target. Persist a v2
config with `scripts/configure_target.py` before operating the VM.

## Endpoint Model

VirtualKD exposes a stable kernel-debug pipe for each VM, such as:

```text
\\.\pipe\kd_win10_lab
```

Bind this as `target.kd_pipe`; do not require its name to change after a
snapshot restore. The harness gives the WinDbg extension a separate unique
MCP endpoint:

```text
\\.\pipe\windbgmcp-win10-lab
```

The bundled windbg-mcp 2.0 pair must use the same endpoint on both sides:

```text
0: kd> !mcpext.start windbgmcp-win10-lab
windbg-mcp.exe --pipe windbgmcp-win10-lab
```

Each WinDbg/extension/host pair accepts one connection, while pairs with
different endpoints run concurrently. `wm_session.pipe_endpoint` proves which
target answered. The host also pins `bridge_instance_id`, preventing a reused
name from silently switching to another WinDbg instance.

## Host Setup

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-host.ps1
```

The script self-elevates, performs bounded path discovery, sets:

```text
HKLM\Software\VirtualKD-Redux\Monitor\AutoInvokeDebugger = 0
HKLM\Software\VirtualKD-Redux\Monitor\DebuggerType = 2
HKLM\Software\VirtualKD-Redux\Monitor\InitialBreakIn = 1
HKLM\Software\VirtualKD-Redux\Monitor\WaitForOS = 1
```

It restarts `vmmon64.exe` only when host settings changed or duplicate
instances exist. Interactive target sessions may already be using vmmon, so
do not rerun host setup during normal parallel testing.

## Session Startup Internals

`lab_start` performs these operations under the host startup lock:

1. Validate the target and host paths.
2. Ensure exactly one `vmmon64.exe` exists.
3. Stop only the selected VM if it is running.
4. Restore its configured snapshot and start it if necessary.
5. Wait for the configured stable `kd_pipe`.
6. Launch classic GUI WinDbg with a unique log and:

```text
-b -c ".load <mcpext.dll>; !mcpext.start <mcp_pipe>; g"
-k com:pipe,port=<kd_pipe>,resets=0,reconnect
```

7. Wait for `mcp_pipe` and require `wm_session.attached=true`.
8. Save target-scoped PID, pipes, log path, and state.

The lock is released after binding. Existing sessions continue concurrently.

## Driver Test Internals

`driver_test` waits for VMware Tools, copies the `.sys`, deletes stale service
state, creates a demand-start kernel service, and starts it.

For `expect=crash`, the guest command and debugger observation overlap. The
bugcheck state is persistent, so the high-level tool confirms it through
`wm_session` even when a VirtualKD version does not push a `bugcheck` event.
It then calls `wm_analyze_crash` and writes full raw output under `logs`.

For `expect=success`, it verifies module load, resumes the guest, stops and
deletes the service, then verifies module unload. Both paths call `lab_reset`
in a cleanup block.

## Failure Map

`config_missing` or `config_incomplete`:
Run `configure_target.py`. Do not search for another VM or guess credentials.

`host_setup_required`, `vmmon_missing`, or `vmmon_state`:
Run `setup-host.ps1` outside active sessions, then rerun `lab_doctor`.

`kd_pipe_timeout`:
Confirm the target's explicit `kd_pipe`, baseline state, and that vmmon was
running before restore. Do not select one of another running VM's pipes.

`mcp_pipe_busy`:
Call `lab_reset` for that target or assign it a unique `mcp_pipe`. Do not kill
other target debuggers.

`windbg_bridge_timeout` or `debugger_not_attached`:
Read the returned WinDbg log. Verify `-b`, the bundled DLL path, the target
endpoint argument, and classic WinDbg rather than Preview.

`vmware_tools_timeout`:
Confirm the guest was running (`g` in WinDbg), VMware Tools is installed, and
the baseline was captured after boot.

`command_failed` for a guest operation:
Validate the configured guest account with one authenticated operation. Do
not try common passwords or host usernames.

## Raw Debug Bridge

Use the one-shot helper only while diagnosing the high-level layer:

```powershell
py -3.11 scripts\invoke-windbg-mcp.py --pipe <mcp_pipe> wm_session
py -3.11 scripts\invoke-windbg-mcp.py --pipe <mcp_pipe> wm_run_cmd "lm m nt"
```

The 2.0 lifecycle tools have distinct meanings:

- `wm_detach`: detach the target and keep the bridge running.
- `wm_shutdown`: stop the bridge after returning its response; leave target
  attachment unchanged.
- `wm_exit`: deprecated alias for `wm_detach`.

Use `wm_shutdown` before terminating the target-scoped WinDbg process during
reset. Restart the native MCP host after a deliberate extension restart,
because the host pins the original bridge instance.
