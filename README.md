# windows-drv-harness

Self-contained AI skill bundle for Windows kernel driver testing with VMware
Workstation, VirtualKD-Redux, WinDbg, `windbg-mcp`, and `vmware-mcp`.

The useful payload lives under one skill directory:

```text
skills/windows-drv-harness/
  SKILL.md
  windbg-mcp/mcpext.dll
  windbg-mcp/windbg-mcp.exe
  vmware-mcp/
  windows-drv-harness.config.example.json
  windows-drv-harness.config.schema.json
```

There is no extra high-level harness MCP server. The AI reads the skill and
directly uses `windbg-mcp`, `vmware-mcp` or `vmrun.exe`, and bounded
PowerShell.

## What It Does

The skill gives an AI agent a closed loop for driver testing:

```text
build driver -> restore VirtualKD-ready snapshot -> deploy .sys ->
load driver -> collect WinDbg/guest evidence -> unload -> revert -> patch code
```

The key is procedural correctness: `vmmon64.exe` must be running before the VM
is restored, VirtualKD must launch WinDbg with `mcpext.dll`, and the agent must
use `windbg-mcp` to read debugger state instead of guessing from screenshots.

## Requirements

- Windows host
- VMware Workstation Pro
- VirtualKD-Redux installed on host and guest
- Windows guest VM with VMware Tools
- A baseline VMware snapshot that already enters the VirtualKD two-machine
  kernel debugging path when restored
- Python 3.10+ for `vmware-mcp`
- Administrator/elevated agent session for HKLM registry writes and reliable
  `vmmon64.exe` control

## Quick Start

```powershell
git clone --recursive https://github.com/Letenz/driver-harness-mcp.git
cd driver-harness-mcp

$skill = ".\skills\windows-drv-harness"
Copy-Item "$skill\windows-drv-harness.config.example.json" "$skill\windows-drv-harness.config.json"
```

`windows-drv-harness.config.json` is gitignored. Put VM paths, snapshot
name, guest credentials, and tool paths there. Prefer `${env:VAR_NAME}` for
passwords.

Install `vmware-mcp` if you want MCP control of VMware:

```powershell
py -3.11 -m venv "$skill\vmware-mcp\.venv"
& "$skill\vmware-mcp\.venv\Scripts\python.exe" -m pip install -U pip
& "$skill\vmware-mcp\.venv\Scripts\python.exe" -m pip install -e "$skill\vmware-mcp"
```

`windbg-mcp.exe` is native and runs directly from
`skills\windows-drv-harness\windbg-mcp\windbg-mcp.exe`.

## Prompt Examples

Use this prompt when handing the repo to an AI agent:

```text
Use skills/windows-drv-harness/SKILL.md as the operating manual. Resolve
tool paths relative to that skill directory. Do not look for an extra harness
MCP server. Use windbg-mcp for debugger state and commands, vmware-mcp or
vmrun for VMware operations, and bounded PowerShell for vmmon/VirtualKD
registry work. Run the skill's preflight gate before any vmrun operation:
verify VirtualKD registry, restart vmmon64.exe, close stale WinDbg, then wait
for the windbgmcp pipe after restore/start. Do not scan whole drives; ask me
for missing paths after bounded probing fails. Do not store plaintext
passwords in config. Ask before registering MCP servers in my current client.
```

For a driver test:

```text
Build my driver, restore the VirtualKD-ready snapshot, copy the .sys to the
guest, load it with sc.exe, collect wm_session/wm_run_cmd evidence, unload it,
revert the snapshot, and patch the smallest code area if the test fails.
```

## Notes

- `vmmon64.exe` must run before restoring a VirtualKD snapshot.
- VirtualKD registry must use `DebuggerType=2` with a custom WinDbg command
  that loads `mcpext.dll` and runs `!mcpext.start`.
- `mcpext.dll` accepts one pipe client at a time.
- Old WinDbg windows should be closed before each restore if their command line
  shows `mcpext.dll`, `windbgmcpExt.dll`, `!mcpext.start`, `!mcpstart`, or the
  `windbgmcp` pipe.
- Do not commit `windows-drv-harness.config.json`.

## License

MIT. Third-party submodules keep their own licenses.
