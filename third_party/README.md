# third_party/

This directory holds Git submodules for the MCP servers we depend on:

- `vmware-mcp/` — submodule of [`ZacharyZcR/vmware-mcp`](https://github.com/ZacharyZcR/vmware-mcp)
- `windbg-ext-mcp/` — submodule of [`Letenz/windbg-ext-mcp`](https://github.com/Letenz/windbg-ext-mcp)
  (a fork of [`NadavLor/windbg-ext-mcp`](https://github.com/NadavLor/windbg-ext-mcp) with two extra patches:
  SDDL pipe ACL + BreakInHandler)

Submodules are not initialized until you run:

```powershell
git submodule update --init --recursive
```

…or use `git clone --recursive` when you cloned this repo.

`installer\install.ps1` will do this for you automatically.
