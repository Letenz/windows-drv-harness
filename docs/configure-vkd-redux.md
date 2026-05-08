# Configure VirtualKD-Redux for auto-launching the MCP-enabled WinDbg

This is one of the trickiest parts of the setup. Read this carefully — we
spent a half day debugging registry semantics so you don't have to.

## What we want

When VirtualKD-Redux's `vmmon64.exe` detects a debug-enabled guest VM, it
should automatically:

1. Launch **WinDbg Preview** (`DbgX.Shell.exe`) with the right pipe arguments
2. Pass `-c ".load <path>\windbgmcpExt.dll; !mcpstart"` to autoload our extension
3. Land in a "broken" state ready for the AI to drive

## The registry — `HKLM\Software\VirtualKD-Redux\Monitor`

> ⚠️ **Important: write to `HKLM`, NOT `HKCU`.**
> `vmmon64.exe` is started elevated (UAC prompt), and once elevated it reads
> the machine hive (`HKLM`). Editing only `HKCU` will silently have no effect.

### Required values

| Name | Type | Value | Why |
|---|---|---|---|
| `DebuggerType` | `REG_DWORD` | `2` | Means "Custom". `0`=KD, `1`=classic windbg.exe, `3`=WinDbg Preview default. **Only `2` honors `CustomDebuggerTemplate`.** |
| `CustomDebuggerTemplate` | `REG_SZ` | (see below) | Command line for launching the debugger |
| `AutoInvokeDebugger` | `REG_DWORD` | `1` | Auto-launch when a VM appears |
| `InitialBreakIn` | `REG_DWORD` | `1` | Pass `-d` (initial break) |
| `WaitForOS` | `REG_DWORD` | `1` | Wait for the guest OS to be detectable |
| `PreviewPath` | `REG_SZ` | (your sideload path, optional) | Used if you point `$(toolspath)` style references |

### `CustomDebuggerTemplate` value

The exact string we recommend (adjust paths to your machine):

```
"C:\Path\To\WinDbg\DbgX.Shell.exe" -k com:pipe,port=$(pipename),resets=0,reconnect -d -c ".load C:\Path\To\windbgmcpExt.dll; !mcpstart"
```

Variables substituted by VKD at launch time:
- `$(pipename)` — full pipe name like `\\.\pipe\kd_<vmname>`
- `$(toolspath)` — value of the `ToolsPath` field in the registry

> 💡 The installer (`installer/steps/write-registry.ps1`) generates this string
> from your detected paths automatically. You usually don't need to type it
> by hand.

## Mistakes we hit (and you might too)

### 1. Editing `HKCU` instead of `HKLM`
`vmmon64.exe` is elevated → reads `HKLM`. UI changes via the GUI write to both;
manual edits via `regedit` only update one. **Use `HKLM` to be safe.**

### 2. `DebuggerType=1` does not use `CustomDebuggerTemplate`
The radio buttons in `vmmon64`'s GUI map to:
- `0` → `KD.EXE`
- `1` → `WINDBG.EXE` (the classic, not Preview)
- `2` → **`Custom:` ← this is what we want**
- `3` → `WinDbg Preview`

Source: [`regconfig.h`](https://github.com/4d61726b/VirtualKD-Redux/blob/master/VirtualKD-Redux/Lib/regconfig.h).
Switching to `2` is what makes the custom command line take effect.

### 3. `WinDbg Preview (1.2601…)` vs sideloaded `1.1910…`
If you have **both** the Microsoft Store version of WinDbg Preview and a sideloaded copy,
`vmmon64`'s default behavior may pick whichever it finds first. Use a `Custom` template
with the **absolute path** to the version you want — that way there's no ambiguity.

### 4. Restart `vmmon64.exe` after registry edits
Settings are read **once at startup**. If you change anything in the registry,
kill and re-launch `vmmon64.exe` (it must be elevated).

```powershell
# Kill (needs admin)
taskkill /IM vmmon64.exe /F

# Relaunch (will prompt for UAC)
Start-Process "C:\Path\To\VirtualKD-Redux\vmmon64.exe"
```

### 5. WinDbg Preview supports `-c`, but not `$$><file.txt`
- ✅ `-c "cmd1; cmd2"` works (semicolon-separated single string)
- ❌ `-c "$$><script.txt"` is a **classic windbg** feature, not Preview

If you need many startup commands, just chain them with `;`.

## Verifying it works

After restarting `vmmon64`, start your guest VM. Within 20–25 seconds you should see:

1. A new `DbgX.Shell.exe` process with window title containing your VM's pipe name
2. Pipe `\\.\pipe\windbgmcp` exists (check via `[IO.Directory]::GetFiles('\\.\pipe\')` in PowerShell)
3. The extension DLL is locked (loaded by `EngHost.exe`)

The doctor script automates these checks:

```powershell
powershell -ExecutionPolicy Bypass -File installer\doctor.ps1
```

## Rollback

To undo all our changes and restore VirtualKD's defaults, run:

```powershell
powershell -ExecutionPolicy Bypass -File installer\uninstall.ps1
```

This restores both `HKCU` and `HKLM` `VirtualKD-Redux\Monitor` keys to a sane default.
