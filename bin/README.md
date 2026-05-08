# bin/

Pre-compiled binaries shipped with this repository, so users do not need
a working C++ build environment to get started.

## What is in here

| File | Size | Description |
|---|---|---|
| `windbgmcpExt.dll` | ~526 KB | WinDbg extension that exposes a JSON-over-named-pipe interface used by the MCP server. Loaded by WinDbg via `.load`. |
| `windbgmcpExt.dll.sha256` | — | SHA-256 checksum of the DLL above. |

## Source of truth

The DLL is built from our fork of upstream `windbg-ext-mcp`:

- Repo:   https://github.com/Letenz/windbg-ext-mcp
- Branch: `driver-harness`
- Commit: `48f044a` (initial v0.1.0-dh.1 release)

The same source is included in this repository as a Git submodule:

```
third_party/windbg-ext-mcp/
```

So `bin/windbgmcpExt.dll` and `third_party/windbg-ext-mcp/` always
point at the same source code. The DLL is a precompiled artifact of
that source, nothing more.

## How it was built

- Toolset:    MSVC v143 (Visual Studio 2022)
- SDK:        Windows 10 SDK `10.0.22621.0`
- Platform:   x64
- Configuration: Release
- C runtime:  `/MT` (statically linked, no VC++ Redistributable needed on target machines)
- Debug info: stripped (`<GenerateDebugInformation>false</GenerateDebugInformation>` + `<DebugInformationFormat>None</DebugInformationFormat>`)

Resulting imports:

```
dbgeng.dll
KERNEL32.dll
ADVAPI32.dll
```

That is, just OS-supplied DLLs. No third-party runtime is required.

## How to verify integrity

```powershell
Get-FileHash bin\windbgmcpExt.dll -Algorithm SHA256
# Should match the hash recorded in windbgmcpExt.dll.sha256
```

## How to rebuild it yourself

If you do not trust the precompiled binary, you can rebuild it from
source. You need Visual Studio 2022 with the C++ Desktop workload and
the Windows 10 SDK.

```powershell
# from the repo root
git submodule update --init --recursive

cd third_party\windbg-ext-mcp\extension
msbuild windbgmcpExt.vcxproj `
    /t:Rebuild `
    /p:Configuration=Release `
    /p:Platform=x64

# Output:
#   third_party\windbg-ext-mcp\extension\build\x64\Release\windbgmcpExt.dll
```

Or use the installer with the `-Build` switch:

```powershell
.\installer\install.ps1 -Build
```

The build will only succeed if you do **not** currently have WinDbg
loaded with `windbgmcpExt.dll` (the file would be locked). If you see
`LNK1104`, run `!mcpstop` then `.unload windbgmcpExt` in WinDbg first,
or simply close WinDbg.

## Why ship a binary at all?

The single highest-impact thing this project promises is **30 minutes
from clone to working AI-driven kernel-driver test loop**. Forcing
every newcomer to install Visual Studio just to obtain a 526 KB DLL
makes that promise impossible to keep.

The binary is small, the source is right next door (`third_party/`),
and the SHA-256 is recorded in this directory. You do not have to
trust us; you can verify, or rebuild and replace.
