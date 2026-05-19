# windows-drv-harness

[中文说明](README.zh-CN.md)

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

There is also a small human-facing sample driver:

```text
example/HelloWorld/
  README.md
  HelloWorld.sln
  HelloWorld/HelloWorld.c
  HelloWorld/HelloWorld.inf
  HelloWorld/HelloWorld.vcxproj
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
git clone --recursive https://github.com/Letenz/windows-drv-harness.git
cd windows-drv-harness

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
disable VirtualKD auto debugger launch, ensure exactly one vmmon64.exe is
running, close stale KD/WinDbg, restore/start the VM, wait for the new
VirtualKD main KD pipe, then launch GUI WinDbg against that pipe and wait for
the windbgmcp pipe. Use the GUI WinDbg window,
debugger log, and windbg-mcp tools for progress visibility. Do not scan whole
drives; ask me for the VMX path and any missing paths after
bounded probing fails. Do not choose a VM from vmrun list without my explicit
confirmation. Do not store plaintext passwords in config. Ask before
registering MCP servers in my current client.
```

For a driver test:

```text
Build my driver, restore the VirtualKD-ready snapshot, copy the .sys to the
guest, load it with sc.exe, collect wm_session/wm_run_cmd evidence, unload it,
revert the snapshot, and patch the smallest code area if the test fails.
```

## Example Driver

`example/HelloWorld` is an intentionally crashing sample driver. Use it to test
whether an AI agent can run the whole harness loop, not just build a driver.
The original local test project was misspelled `HelloWord`; this repository
uses the corrected `HelloWorld` name throughout the example.

The intended demo flow is:

```text
ask the agent to build example/HelloWorld ->
agent restores the VirtualKD-ready VMware snapshot ->
agent copies HelloWorld.sys into the guest ->
agent loads it with sc.exe and observes the expected BSOD ->
agent uses WinDbg MCP to analyze the bugcheck/root cause ->
agent patches the driver source and rebuilds ->
agent restores the snapshot again and retests the fixed .sys ->
agent verifies the driver no longer BSODs and can unload cleanly
```

The seeded bug is a `NULL` write in `DriverEntry`. A correct first test should
produce bugcheck `0x7E` `SYSTEM_THREAD_EXCEPTION_NOT_HANDLED` with
`STATUS_ACCESS_VIOLATION`. A correct fix removes that bad write, rebuilds the
driver, reruns the VMware test, and confirms `sc start`, `sc stop`, and
`sc delete` complete without a new BSOD. See `example/HelloWorld/README.md`
for the exact prompt and expected evidence.

## Notes

- `vmmon64.exe` must run before restoring a VirtualKD snapshot.
- VirtualKD auto debugger launch should be disabled; the agent launches
  classic `windbg.exe -b ...` manually after the VirtualKD main KD pipe
  appears. Unless the user explicitly gives another kernel debugger pipe, use
  the VirtualKD `\\.\pipe\kd_*` pipe for WinDbg.
- `mcpext.dll` accepts one pipe client at a time.
- Old KD/WinDbg processes should be closed before each restore if their command line
  shows `mcpext.dll`, `windbgmcpExt.dll`, `!mcpext.start`, `!mcpstart`, or the
  `windbgmcp` pipe.
- Do not commit `windows-drv-harness.config.json`.

## License

MIT. Third-party submodules keep their own licenses.
