# windows-drv-harness

[中文说明](README.zh-CN.md)

An AI-oriented Windows kernel-driver test harness for VMware Workstation,
VirtualKD-Redux, and WinDbg. Version 2 gives small models one high-level MCP
server instead of asking them to coordinate raw VMware commands, debugger
processes, pipes, credentials, and snapshot cleanup.

## Architecture

```text
AI agent
  -> windows-drv-harness MCP (7 small, task-level tools)
       -> target profile + target-scoped state
       -> vmrun.exe
       -> WinDbg + mcpext.dll on a unique MCP pipe
       -> windbg-mcp.exe 2.0 on the same pipe
```

Runtime configuration is outside the installed skill:

```text
%LOCALAPPDATA%\windows-drv-harness\
  config.json
  state\
  logs\
```

One config can hold any number of VM targets. Each target has its own VMX,
snapshot, guest account, stable VirtualKD KD pipe, and unique windbg-mcp pipe.
Target startups are briefly serialized while binding a KD pipe; attached
WinDbg/MCP sessions can then run in parallel.

## Requirements

- Windows host with Python 3.10+
- VMware Workstation and `vmrun.exe`
- VirtualKD-Redux on host and guest
- Classic x64 `windbg.exe`
- WDK/Visual Studio when building drivers
- VMware Tools in each guest

The baseline snapshot must be saved after the guest has booted, VMware Tools
is running, and classic WinDbg has successfully attached to the kernel target
through VirtualKD/KDNET. A cold snapshot that never reached a verified
two-machine debugging state is not a valid baseline.

## Quick Start

```powershell
git clone --recursive https://github.com/Letenz/windows-drv-harness.git
cd windows-drv-harness

$skill = ".\skills\windows-drv-harness"
powershell -ExecutionPolicy Bypass -File "$skill\scripts\install-mcp.ps1"

py -3.11 "$skill\scripts\configure_target.py" `
  --target win10-lab `
  --vmx "D:\VMs\win10-lab\win10-lab.vmx" `
  --snapshot baseline-debug-ready `
  --kd-pipe kd_win10_lab `
  --guest-user testadmin `
  --guest-deploy-dir "C:\Users\testadmin\Desktop" `
  --make-default

powershell -ExecutionPolicy Bypass -File "$skill\scripts\setup-host.ps1"
py -3.11 "$skill\scripts\harness_cli.py" doctor --target win10-lab
```

`configure_target.py` prompts for the guest password without placing it on the
command line. The machine-local config may store plaintext credentials or an
`${env:VAR_NAME}` reference; harness output always redacts secret fields.

`setup-host.ps1` self-elevates when necessary. It disables VirtualKD automatic
debugger launch, records bounded-discovery tool paths, and ensures one global
`vmmon64.exe`. Run it as one-time host setup, not before every parallel target.

After the smoke check, register the single high-level server when desired:

```powershell
powershell -ExecutionPolicy Bypass -File "$skill\scripts\detect-mcp.ps1"
powershell -ExecutionPolicy Bypass -File "$skill\scripts\register-mcp.ps1" -Apply
```

For a custom agent, point its stdio MCP entry at:

```text
py -3.11 <SKILL_DIR>\scripts\harness_mcp.py
```

The server is dependency-free and can be checked without changing any client:

```powershell
py -3.11 "$skill\scripts\smoke-mcp-server.py" --server harness
```

## MCP Tools

| Tool | Purpose |
|---|---|
| `lab_list_targets` | List profiles without credentials |
| `lab_doctor` | Read-only target readiness check |
| `lab_start` | Open a target-scoped interactive debugger session |
| `driver_build` | Select WDK-compatible MSBuild and return the `.sys` |
| `driver_test` | Deploy, test, collect evidence, and restore baseline |
| `debug_run` | Run one extra WinDbg command when needed |
| `lab_reset` | Reset only the selected target |

Every result contains a stable `status` and `next_action`. `driver_test` uses
`expect="crash"` for a known failing build and `expect="success"` after the
fix. It attempts baseline cleanup on every exit path.

## Multiple Targets

Run `configure_target.py` again with another `--target`, `--vmx`, `--kd-pipe`,
and guest account. Give every target a unique MCP pipe; when omitted it is
derived as `windbgmcp-<target>`.

The VirtualKD `kd_pipe` is a stable observed binding and must be explicit. It
is not assumed to get a new name after snapshot restore. The separate
`mcp_pipe` routes one WinDbg 2.0 bridge to one target and allows parallel
sessions without exposing many MCP server registrations to the model.

## HelloWorld Example

`example/HelloWorld` deliberately writes through `NULL` in `DriverEntry`.
Give an agent this compact task:

```text
Use the windows-drv-harness tools on example\HelloWorld. Build it, run the
first driver test expecting a crash, use the returned WinDbg evidence to make
the smallest source fix, rebuild, and run a success test. Finish only when the
service loads/unloads cleanly and cleanup reports the VM reverted.
```

Expected first result: bugcheck `0x7E`, access violation, probable culprit
`HelloWorld.sys`. Expected fixed result: create/start/stop/delete succeed,
WinDbg sees the module load and unload, and the configured baseline is
restored.

## Bundled WinDbg Bridge

The skill vendors `windbg-mcp.exe` and `mcpext.dll` 2.0 from
[Letenz/windbg-mcp](https://github.com/Letenz/windbg-mcp). Version 2 supports
one named endpoint per WinDbg instance, explicit detach/shutdown semantics,
and bridge-instance pinning. Exact source commit and artifact hashes are in
`skills/windows-drv-harness/windbg-mcp/build-manifest.json`.

`vmware-mcp` remains available as a submodule for advanced/raw operation, but
small models should use the high-level harness server.

## Development Checks

```powershell
py -3.11 -m unittest discover -s tests -v
py -3.11 skills\windows-drv-harness\scripts\smoke-mcp-server.py --server harness
py -3.11 skills\windows-drv-harness\scripts\smoke-mcp-server.py --server windbg --pipe windbgmcp-smoke
```

Large logs and all machine state remain under `%LOCALAPPDATA%`; neither should
be committed.

## License

MIT. Third-party submodules retain their own licenses.
