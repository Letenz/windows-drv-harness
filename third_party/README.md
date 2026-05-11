# third_party/

Git submodules for the MCP servers and extensions this project builds upon.

| Submodule | Source |
|---|---|
| `vmware-mcp/` | [ZacharyZcR/vmware-mcp](https://github.com/ZacharyZcR/vmware-mcp) — VMware Workstation control via MCP |
| `windbg-ext-mcp/` | [Letenz/windbg-ext-mcp](https://github.com/Letenz/windbg-ext-mcp) — fork of [NadavLor/windbg-ext-mcp](https://github.com/NadavLor/windbg-ext-mcp) with two extra patches (SDDL pipe ACL + `BreakInHandler`) required for headless AI workflows |

`vmware-mcp/` is an upstream submodule. Driver-harness applies the small patch
in `third_party/patches/vmware-mcp-structured-guest-args.patch` during
`installer\install.ps1`, so guest `runProgramInGuest` arguments can be passed
as a JSON array instead of fragile shell text.

## Why submodules instead of vendored copies

- Upstream projects evolve — we track specific commits so breaking
  changes upstream do not silently break us.
- Users who want to audit or modify the extension source can do so
  directly in `third_party/windbg-ext-mcp/`, and a local `msbuild`
  there produces exactly the same DLL that ships in `bin/`.
- For the fork, any improvements we make can be PR'd back to the
  upstream project later.

## Version pinning policy

Submodules are pinned to **specific commit SHAs**, not branches. This
means `git submodule update` will always give you exactly the code we
have tested against. If you want to bump a submodule, do it explicitly:

```powershell
cd third_party\<name>
git fetch
git checkout <new-commit>
cd ..\..
git add third_party\<name>
git commit -m "bump <name> to <new-commit>"
```

## Initialization

If you did not clone with `--recursive`:

```powershell
git submodule update --init --recursive
```

`installer\install.ps1` does this automatically as step 02.

## Relationship to `bin/`

The file `bin\windbgmcpExt.dll` is a precompiled build of exactly the
commit that `third_party\windbg-ext-mcp/` is pinned to. You can always
rebuild it yourself:

```powershell
installer\install.ps1 -Build
```

…or manually:

```powershell
cd third_party\windbg-ext-mcp\extension
msbuild windbgmcpExt.vcxproj /t:Rebuild /p:Configuration=Release /p:Platform=x64
```

See `bin\README.md` for verification and integrity details.
