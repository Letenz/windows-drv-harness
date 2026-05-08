# Common pitfalls (AI-targeted)

If any of these symptoms show up, apply the matching fix before trying again.
This is a **living document**; add new pitfalls as they're discovered.

## Host-side

### P-H1. `vmmon64.exe` ignores registry changes
**Symptom:** You wrote new `CustomDebuggerTemplate`, restarted the VM, but VKD still launches the old thing.
**Cause:** VKD reads settings **once at startup** of `vmmon64`. You need to kill and relaunch it.
**Fix:**
```powershell
taskkill /IM vmmon64.exe /F
Start-Process "C:\Path\To\VirtualKD-Redux\vmmon64.exe"
```

### P-H2. HKCU edits don't take effect
**Symptom:** Same as above, even after `vmmon64` restart.
**Cause:** `vmmon64` is UAC-elevated and reads **`HKLM`**, not `HKCU`.
**Fix:** Write your changes to `HKLM\Software\VirtualKD-Redux\Monitor`. Needs admin PowerShell.

### P-H3. Pipe `Access is denied (5)`
**Symptom:** MCP client can't connect to `\\.\pipe\windbgmcp`.
**Cause:** WinDbg is elevated, your client is not; default pipe ACL requires same IL.
**Fix:** Use `Letenz/windbg-ext-mcp` (has SDDL patch), not upstream `NadavLor/windbg-ext-mcp`.

### P-H4. DLL path can't be loaded (`.load fails`)
**Symptom:** `-c ".load F:\path\windbgmcpExt.dll" fails`.
**Possible causes:**
- Path contains non-ASCII characters (WinDbg Preview has trouble)
- File doesn't exist at the expected path
- File is 32-bit but WinDbg is 64-bit, or vice versa

**Fix:** Use pure ASCII path, verify file exists, match bitness.

### P-H5. `MSBuild` not found but VS is installed
**Cause:** VS at non-default path; `vswhere.exe` won't find it.
**Fix:** Set `$env:DRIVER_HARNESS_MSBUILD` to the full path, or edit `installer/steps/build-windbg-ext.ps1`.

## Guest-side

### P-G1. `vmrun -gu/-gp` says "Command requires valid user name and password"
**Cause:** Empty password rejected by VMware Tools, regardless of Windows itself.
**Fix:** Set a non-empty password in the guest; recreate the baseline snapshot.

### P-G2. Guest first-run vmrun call is very slow (~80s)
**Cause:** VMware Tools guest auth service cold start.
**Fix:** In `recover_to_clean_state`, issue a cheap warm-up call like `file_exists C:\` right after `start`. Absorbs the latency.

### P-G3. KDNET is configured but won't connect
**Cause:** Host firewall blocks UDP 50000, or `hostip` in bcdedit points to the wrong NIC.
**Fix:**
- Host: `New-NetFirewallRule -DisplayName "KDNET" -Direction Inbound -Protocol UDP -LocalPort 50000 -Action Allow` (admin)
- Guest: `bcdedit /dbgsettings net hostip:<correct_vmnet_host_ip> port:50000 key:...`

## WinDbg / debugger

### P-W1. `.crash` returns "Kernel transport in use, packet write failed"
**Cause:** Target is running; `.crash` requires broken state.
**Fix:** `break_in` first.

### P-W2. `break_in` hangs indefinitely
**Possible causes:**
- You're using upstream `windbg-ext-mcp` without our `BreakInHandler` — it doesn't have `break_in`.
- The fresh `IDebugClient` design is wrong and blocks. Our v2 implementation polls `GetExecutionStatus`; see `enhanced_command_handlers.cpp`.

**Fix:** Update to `Letenz/windbg-ext-mcp` (or our v0.1 release).

### P-W3. `~` (list threads) errors out in kernel mode
**Cause:** Kernel mode uses different thread semantics. `~` is a user-mode command.
**Fix:** Use `!thread`, `!process -1 0`, or `!for_each_thread`.

### P-W4. `lm 1` syntax error
**Cause:** `lm` doesn't accept numeric arguments. You probably meant `lm m <module>` or `lm` with a filter.
**Fix:** Use `lm` alone, or `lm m nt`, or `lm k` for kernel modules.

### P-W5. Commands that succeed but return empty output look like errors
**Cause:** Some WinDbg commands (`bp`, `g`, `eb`) don't print anything on success.
**Fix:** Our `ExecuteCommandHandler` whitelists these and emits friendly confirmations. If your version doesn't, treat "empty success" as success.

## MCP / AI-client

### P-M1. Client loads MCP servers but finds no tools
**Cause:** Wrong Python version in venv, missing dependencies, or stale import cache.
**Fix:**
```powershell
cd <mcp_dir>
python -m <module_name> --help   # run manually first to see errors
```

### P-M2. Cursor/Claude Code CLI "MCP server disconnected"
**Cause:** Server crashed. Check the client's MCP log or run the server manually.
**Fix:** Most commonly a Python import error or pipe connection failure at startup.

### P-M3. Long-running commands time out
**Cause:** Default 30s timeout in `windbg-ext-mcp` is too short for `!process 0 0` etc.
**Fix:** Pass `timeout_ms` explicitly in the command args.

---

If you hit a pitfall not listed here, **please document it** in your report to the user
so we can add it. Include: exact symptom, reproduction steps, your workaround.
