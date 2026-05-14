# driver-harness-mcp

AI-operated Windows kernel driver test harness for VMware Workstation,
VirtualKD-Redux, WinDbg, and MCP.

The repo is intentionally small:

```text
skills/kernel-driver-testing/SKILL.md   AI operating manual
driver-harness-mcp/                     high-level MCP server
third_party/vmware-mcp/                 VMware MCP submodule
third_party/windbg-ext-mcp/             WinDbg MCP submodule and extension source
bin/windbgmcpExt.dll                    prebuilt WinDbg MCP extension
driver-harness.config.example.json      user config template
driver-harness.config.schema.json       config schema
```

## What It Does

The harness gives an AI agent a closed loop for driver testing:

```text
build driver -> restore debug-ready VM snapshot -> deploy .sys ->
load driver -> collect WinDbg/guest evidence -> unload -> revert -> patch code
```

The agent should use the single skill at
`skills/kernel-driver-testing/SKILL.md`. That file contains the environment
setup, VirtualKD rules, MCP registration template, and tool-call order.

## Requirements

- Windows host
- VMware Workstation Pro
- VirtualKD-Redux installed on host and guest
- Windows guest VM with VMware Tools
- A baseline VMware snapshot that already enters the VirtualKD two-machine
  kernel debugging path when restored
- Python 3.11+
- Administrator/elevated agent session for HKLM registry writes and reliable
  `vmmon64.exe` control

## Quick Start

```powershell
git clone --recursive https://github.com/Letenz/driver-harness-mcp.git
cd driver-harness-mcp

# Let the AI follow the skill for venv setup, config creation, registry setup,
# vmmon startup, MCP registration, and the first driver test.
```

Create local config from the template:

```powershell
Copy-Item .\driver-harness.config.example.json .\driver-harness.config.json
```

`driver-harness.config.json` is gitignored. Put VM paths, snapshot name, guest
credentials, and tool paths there. Prefer `${env:VAR_NAME}` for passwords.

## Prompt Examples

Use this prompt when handing the repo to an AI agent:

```text
Use the skill at skills/kernel-driver-testing/SKILL.md as the only operating
manual. Diagnose the environment first. Do not restore or start the VM until
vmmon64.exe is running. Probe missing tool paths only from explicit input,
config, environment variables, registry values, and fixed default paths. Do not
scan whole drives. Ask me for vmmon64.exe if bounded probing fails. After setup
is green, ask before registering the skill or MCP servers in my current client.
```

For a driver test:

```text
Build my driver, then call driver-harness-mcp.run_driver_load_verify on the
built .sys. Summarize the evidence. If it fails, patch the smallest relevant
code area and rerun once.
```

For first-time setup:

```text
Help me create driver-harness.config.json. Ask only for the VMX path, the
VirtualKD-ready baseline snapshot name, guest admin credentials or env-var
name, and vmmon64.exe path if bounded probing cannot find it.
```

## Notes For Humans

- `vmmon64.exe` must run before restoring a VirtualKD snapshot.
- VirtualKD registry must use `DebuggerType=2` with a custom WinDbg command
  that loads `windbgmcpExt.dll` and runs `!mcpstart`.
- Old WinDbg windows should be closed before each restore; the harness exposes
  `cleanup_windbg_instances` and `exit_windbg` for that.
- Do not commit `driver-harness.config.json`.

## License

MIT. Third-party submodules keep their own licenses.
