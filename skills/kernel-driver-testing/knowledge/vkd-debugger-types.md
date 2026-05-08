# VirtualKD-Redux DebuggerType reference

A quick reference for the `DebuggerType` registry value at
`HKLM\Software\VirtualKD-Redux\Monitor`. Source:
[`regconfig.h`](https://github.com/4d61726b/VirtualKD-Redux/blob/master/VirtualKD-Redux/Lib/regconfig.h).

## Values

| Value | Constant | Launches | Reads `CustomDebuggerTemplate`? |
|---|---|---|---|
| `0` | `DEBUGGER_TYPE_KD` | `<ToolsPath>\kd.exe` | ❌ |
| `1` | `DEBUGGER_TYPE_WINDBG` | `<ToolsPath>\windbg.exe` (classic) | ❌ |
| **`2`** | **`DEBUGGER_TYPE_CUSTOM`** | **Whatever's in `CustomDebuggerTemplate`** | ✅ |
| `3` | `DEBUGGER_TYPE_WINDBGPREVIEW` | Sideloaded or Store WinDbg Preview | ❌ |
| `999` | `DEBUGGER_TYPE_UNKNOWN` | (uninitialized; VKD picks a default at first run) | n/a |

## How VKD decides which to launch

For `2` (Custom):
- Reads `CustomDebuggerTemplate` from registry
- Substitutes `$(toolspath)` with `ToolsPath` field
- Substitutes `$(pipename)` with the actual pipe (e.g. `\\.\pipe\kd_<vmname>`)
- Spawns the resulting command line with `CreateProcessW`

For `3` (Preview):
- Prefers sideloaded path (`PreviewPath` field) if it points to a valid `DbgX.Shell.exe`
- Falls back to the Store-installed Microsoft.WinDbg appx
- Always passes `-k com:pipe,resets=0,reconnect,port=<pipename>` (no `-c` support!)
- Adds `-d` if `InitialBreakIn` is `1`

## Why we use `2`, not `3`

The Preview launcher (`3`) doesn't allow custom flags — we can't pass `-c .load <ext>`.
With `2` we get full control of the command line. Our installer writes:

```
"<sideload preview path>\DbgX.Shell.exe" -k com:pipe,port=$(pipename),resets=0,reconnect -d -c ".load <ext path>; !mcpstart"
```

## Other relevant Monitor values

| Name | Type | Purpose |
|---|---|---|
| `ToolsPath` | `REG_SZ` | Path to debugger tools dir (used by `0`/`1` and as `$(toolspath)`) |
| `PreviewPath` | `REG_SZ` | Path to sideloaded WinDbg Preview (`DbgX.Shell.exe`'s parent dir) |
| `CustomDebuggerTemplate` | `REG_SZ` | The custom command line for `DebuggerType=2` |
| `AutoInvokeDebugger` | `REG_DWORD` | `1` = auto-launch debugger when VM detected |
| `AutoCloseDebugger` | `REG_DWORD` | `1` = close debugger when VM stops (we leave at default) |
| `InitialBreakIn` | `REG_DWORD` | `1` = pass `-d` flag (used by `3` automatically; we add it manually for `2`) |
| `WaitForOS` | `REG_DWORD` | `1` = wait for guest OS detection before launching |
| `DebugLevel` | `REG_DWORD` | Patcher verbosity (0–3) |
| `PatchDelay` | `REG_DWORD` | Seconds to delay patcher init |

## Things that confused us before

1. The GUI radio buttons map 1:1 to `DebuggerType`. The "WinDbg Preview" radio is `3`,
   not `2`. To get a custom command line, you must check **"Custom"** (which is `2`).

2. `vmmon64`'s GUI lets you edit the `CustomDebuggerTemplate` field even when
   `DebuggerType≠2`, but the value is ignored at launch time. The Edit-box being
   filled doesn't mean it's active.

3. Both `HKCU` and `HKLM` paths exist for these keys. `vmmon64` (elevated) reads
   `HKLM`. The standard `vmmon64.exe` GUI seems to write back to whichever it loaded.
   For automation, **just write to `HKLM`** — installer must run as admin.
