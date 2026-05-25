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

## Component Sources

- `windbg-mcp`: source repository is
  [Letenz/windbg-mcp](https://github.com/Letenz/windbg-mcp). This harness
  vendors a known-good `windbg-mcp.exe` and `mcpext.dll` under
  `skills/windows-drv-harness/windbg-mcp/` so an agent can use the debugger
  bridge without cloning or building it during a driver test. When replacing
  these binaries, update the adjacent `.sha256` files too.
- `vmware-mcp`: source repository is
  [ZacharyZcR/vmware-mcp](https://github.com/ZacharyZcR/vmware-mcp). It is
  bundled as the submodule under `skills/windows-drv-harness/vmware-mcp/`.

There is no extra high-level harness MCP server. The AI reads the skill and
directly uses `windbg-mcp`, `vmware-mcp` or `vmrun.exe`, and bounded
PowerShell.

## What It Does

The skill gives an AI agent a closed loop for driver testing:

```text
build driver -> restore VirtualKD-ready snapshot -> deploy .sys ->
load driver -> collect WinDbg/guest evidence -> unload -> revert -> patch code
```

The key is procedural correctness: the baseline snapshot must be captured only
after the guest has booted and classic WinDbg has already attached to the
kernel target through VirtualKD/KDNET at least once; `vmmon64.exe` must be
running before the VM is restored; and the agent must use `windbg-mcp` to read
debugger state instead of guessing from screenshots.

## Requirements

- Windows host
- VMware Workstation Pro
- VirtualKD-Redux installed on host and guest
- Windows guest VM with VMware Tools
- A baseline VMware snapshot captured after the guest has booted, VMware Tools
  is running, VirtualKD/KDNET is configured, and classic WinDbg has successfully
  attached to the kernel target. Do not use a cold/offline snapshot that has
  never reached a verified two-machine debugging state.
- Python 3.10+ for `vmware-mcp`
- Administrator/elevated agent session for HKLM registry writes and reliable
  `vmmon64.exe` control

## Quick Start

```powershell
git clone --recursive https://github.com/Letenz/windows-drv-harness.git
cd windows-drv-harness

$skill = ".\skills\windows-drv-harness"
Copy-Item "$skill\windows-drv-harness.config.example.json" "$skill\windows-drv-harness.config.json"
powershell -ExecutionPolicy Bypass -File "$skill\scripts\detect-mcp.ps1"
```

`windows-drv-harness.config.json` is gitignored. Put VM paths, snapshot
name, guest credentials, and tool paths there before environment checks. Local
plaintext guest passwords are supported when you want a self-contained config;
agents should redact secrets in chat output and never commit this file.

If the current agent already shows `windbg-mcp` and `vmware-mcp` in its
callable tools, use them directly and skip the detection/registration scripts.
If MCP tools are missing, run `scripts\install-mcp.ps1` to prepare local
tooling. It does not add servers to a client MCP list. After explicit user
confirmation, Codex users can run:

```powershell
powershell -ExecutionPolicy Bypass -File "$skill\scripts\install-mcp.ps1"
powershell -ExecutionPolicy Bypass -File "$skill\scripts\register-mcp.ps1" -Apply
```

If registration fails, use the manual commands printed by `detect-mcp.ps1` or
`register-mcp.ps1`.

For a custom agent, the scripts cannot prove that your agent loaded the MCP
server unless your agent exposes its own list/config API. They can still
validate the server side with a client-independent MCP stdio smoke test:

```powershell
py -3 "$skill\scripts\smoke-mcp-server.py" --server windbg
py -3 "$skill\scripts\smoke-mcp-server.py" --server vmware
```

Then add the printed command paths to your custom agent's MCP configuration
and have the agent list tools before any VM operation.

`windbg-mcp.exe` is native and runs directly from
`skills\windows-drv-harness\windbg-mcp\windbg-mcp.exe`.

For shell-only clients, use the bundled one-shot helper instead of creating a
temporary MCP client in the repo root:

```powershell
py -3 .\skills\windows-drv-harness\scripts\invoke-windbg-mcp.py wm_session
py -3 .\skills\windows-drv-harness\scripts\invoke-windbg-mcp.py wm_run_cmd "lm m nt"
```

## Moving To Another Host

The skill folder is portable, but the lab state is not. On a new computer you
must install VMware Workstation, Windows Kits Debuggers, VirtualKD-Redux, and
Python, copy or recreate a VM whose baseline snapshot was saved after boot and
after a verified WinDbg two-machine debugging attach, then create a new local
`windows-drv-harness.config.json` with that machine's VMX, snapshot, tool
paths, symbols path, and guest credentials. If those paths and the prepared
snapshot are valid, the same skill should run there too.

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
confirmation. Fill the local gitignored config first, including guest
credentials for vmrun/vmware-mcp, and redact secrets in chat output. Ask
before registering MCP servers in my current client.
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

Use this task prompt:

```text
Run example\HelloWorld according to skills/windows-drv-harness/SKILL.md.
First reproduce the expected BSOD and report the WinDbg MCP bugcheck/root
cause. Then make the smallest source fix, rebuild, restore the baseline
snapshot, retest, and finish only after sc start/stop/delete succeed and the VM
is reverted.
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
