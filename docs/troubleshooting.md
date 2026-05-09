# Troubleshooting

Symptom → likely cause → fix. Start with `installer\doctor.ps1` first; it
catches most setup issues automatically.

## A. Installer / build phase

### A1. `MSBuild.exe not found`
The installer looks for VS 2022 at default and a few common paths. If you have
VS at a non-standard location, set the env var:
```powershell
$env:DRIVER_HARNESS_MSBUILD = "D:\path\to\MSBuild\Current\Bin\MSBuild.exe"
```
…and rerun the installer.

### A2. `python: command not found` or wrong version
We need Python ≥ 3.11. If you have multiple Pythons, point to the right one:
```powershell
$env:DRIVER_HARNESS_PYTHON = "C:\Python311\python.exe"
```

### A3. `git submodule update` fails with permission errors
You probably forgot to clone with `--recursive`. From the repo root:
```powershell
git submodule update --init --recursive --force
```

### A4. Building the WinDbg extension fails with `LNK1104: cannot open file 'windbgmcpExt.dll'`
WinDbg has the DLL loaded. Either close WinDbg, or:
1. In WinDbg: `!mcpstop`
2. Then: `.unload windbgmcpExt`
3. Re-run the installer

## B. Runtime phase — VKD / WinDbg auto-launch

### B1. WinDbg doesn't auto-launch when the VM starts
Likely culprits, in order:
1. `vmmon64.exe` is not running. Launch it from your VKD-Redux install dir (will UAC prompt).
2. `vmmon64.exe` was running but you edited registry **after** it started — kill and relaunch it.
3. Wrong registry hive — make sure you wrote to **`HKLM`** not `HKCU` (see [`configure-vkd-redux.md`](./configure-vkd-redux.md)).
4. `DebuggerType` is not `2`. Run:
   ```powershell
   reg query "HKLM\Software\VirtualKD-Redux\Monitor" /v DebuggerType
   ```
   The output should be `0x2`.

### B2. WinDbg launches but a different version than expected
Check the `MainWindowTitle` of the spawned `DbgX.Shell.exe`:
```powershell
Get-Process DbgX.Shell | Select Id, MainWindowTitle
```
Compare the version (`WinDbg (1.x.xxxx.xxxxx)`) against your `CustomDebuggerTemplate`.
Common mistake: VKD picks Microsoft Store-installed Preview because `DebuggerType` is still `3`.

### B3. WinDbg launched but `\\.\pipe\windbgmcp` doesn't appear
The `-c .load` only fires after the kernel target is reachable. Check:
1. `\\.\pipe\kd_<vmname>` exists → kernel transport up
2. WinDbg reached the initial break (it should, because we use `-d`)
3. Try `!help` in WinDbg's command window — does the extension show up?

If the extension is loaded but the pipe still missing, run `!mcpstart` manually
in WinDbg's command window and watch its output.

## C. Runtime phase — MCP client connection

### C1. AI client says "MCP server failed to start" or "no tools found"
- Check the AI client's log (varies by client — Claude Code CLI, Cursor, etc.)
- Try running the MCP server manually first to see the real error:
  ```powershell
  cd third_party\windbg-ext-mcp
  python -m mcp_server.server
  ```
- Make sure the venv has `fastmcp==2.5.1` and `pywin32` installed (the installer should do this)
- Stale venv after a Python upgrade is a common cause — delete the `.venv` folder and rerun the installer.

### C2. `Connect failed: Access is denied (5)` on the windbgmcp pipe
Without our SDDL patch, only Administrator clients can connect to a pipe owned by elevated WinDbg.

Check whether the patch is applied:
```powershell
# In the windbg-ext-mcp source, mcp_server.cpp should contain ConvertStringSecurityDescriptorToSecurityDescriptorW
Select-String -Path third_party\windbg-ext-mcp\extension\src\ipc\mcp_server.cpp -Pattern "ConvertStringSecurityDescriptor"
```

If empty, your fork doesn't have the patch — make sure you're using `Letenz/windbg-ext-mcp`,
or `installer\steps\apply-patches.ps1` ran successfully.

### C3. Commands return `Kernel transport in use, packet write failed`
The target is in **running** state and you tried to send a command that requires
**broken** state (like `.crash`, `.dump`, etc.).

Use `BreakInHandler` first:

```python
# Pseudo-code from your AI client
windbg_ext.break_in()        # programmatically interrupts the target
windbg_ext.execute_command(".crash")
windbg_ext.execute_command("!analyze -v")
```

If you don't have `BreakInHandler`, you're using upstream `windbg-ext-mcp`
without our patch — update to our fork.

## Cx. WinDbg command quirks

### Cx1. `~` (list threads) errors out in kernel mode
`~` is user-mode. In kernel mode use `!thread`, `!process -1 0`, or `!for_each_thread`.

### Cx2. `lm 1` or `lm <number>` is a syntax error
`lm` doesn't take numeric arguments. Use `lm` alone, `lm m <module>` (wildcard), or `lm k` (kernel modules).

### Cx3. `bp`, `g`, `eb` look like errors because they return no output
These commands intentionally print nothing on success. Our `ExecuteCommandHandler` whitelists them and emits friendly confirmations; if yours doesn't, treat an empty success as success.

### Cx4. `.load <dll>` fails
Possible causes:
- Path contains non-ASCII characters (WinDbg Preview mangles them)
- File doesn't exist at that path
- Bitness mismatch (32-bit DLL vs 64-bit WinDbg)

Use a pure-ASCII absolute path and verify the file exists.

## D. Guest VM issues

### D1. `vmrun` returns `Command requires valid user name and password for the guest OS`
- vmrun does **not** accept empty passwords — even if the Windows account has none. Set a real password.
- VMware Tools must be running and healthy in the guest (check `vmrun checkToolsState <vmx>`).

### D2. Guest network is broken but `vmrun guest_ip` returns `unknown`
This is normal! `vmrun -gu/-gp` uses VMCI (no network needed). You only need
`guest_ip` if you're using KDNET or doing SMB file transfer.

### D3. After BSOD, the guest doesn't appear in `vmmon64`'s VM list
Re-revert the snapshot. After a hard crash the VKD client state in the guest may
need a clean reload.

### D4. KDNET configured but won't connect
If you're using native KDNET (not VirtualKD-Redux):
- Host firewall blocks UDP 50000 by default. Add an inbound rule (admin shell):
  ```powershell
  New-NetFirewallRule -DisplayName "KDNET" -Direction Inbound -Protocol UDP -LocalPort 50000 -Action Allow
  ```
- `bcdedit /dbgsettings net hostip:...` must point at your **VMnet8 host-side IP** (not the office NIC IP).
  Find it with `Get-NetIPAddress -InterfaceAlias 'VMnet8'`.

## E. Performance / timing

### E1. End-to-end (revert → MCP ready) takes much longer than 25s
Check sequentially:
- `vmrun start` — should be ~10s. If slower, your disk is slow or VMware Tools is being weird.
- `vmrun runProgramInGuest` first call — has a **~80s warm-up** for VMware Tools. Subsequent calls are <1s.
  Workaround: in `recover_to_clean_state`, do a cheap warm-up call (like `file_exists C:\`) right after start.

### E2. KD commands occasionally hang
- WinDbg's command timeout default in `windbg-ext-mcp` is 30s. For heavy commands (`!process 0 0`),
  bump it via `args.timeout_ms`.
- If commands consistently hang, your KD link may be unhealthy — revert the snapshot.

## F. Still stuck?

1. Run `installer\doctor.ps1` and capture the full output.
2. Open an issue with the doctor output, the exact reproduction steps, and the
   error message you saw.

Before posting, please redact any private or sensitive paths, IP addresses,
hostnames, or credentials.
