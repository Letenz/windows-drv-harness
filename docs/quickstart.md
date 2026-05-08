# Quickstart — 30 minutes to your first AI-driven BSOD

This guide takes you from "fresh Windows host" to "AI assistant runs an end-to-end
kernel-patch BSOD test" in about 30 minutes.

## Prerequisites

You need to install these **manually** (the installer won't do it):

| Component | Why | Download |
|---|---|---|
| **VMware Workstation Pro 16+** | Hosts the guest VM | [vmware.com](https://www.vmware.com/products/workstation-pro.html) |
| **A Windows guest VM** | Target for kernel debugging. Win10 19041+ or Win11 recommended. | (your install media) |
| **Windows SDK / Debugging Tools for Windows** | Provides WinDbg Preview (`DbgX.Shell.exe`), debug symbols | [docs.microsoft.com](https://learn.microsoft.com/windows-hardware/drivers/debugger/) |
| **Visual Studio 2022 + Windows SDK** | To compile the WinDbg extension DLL (or skip and use prebuilt release) | [visualstudio.microsoft.com](https://visualstudio.microsoft.com/) |
| **Python 3.11+** | For the MCP servers | [python.org](https://www.python.org/) |
| **Git for Windows** | To clone with submodules | [git-scm.com](https://git-scm.com/) |
| **VirtualKD-Redux 2024.3** | Fast virtual KD transport | [github.com/4d61726b/VirtualKD-Redux/releases](https://github.com/4d61726b/VirtualKD-Redux/releases) |
| **An MCP-capable AI client** | Claude Code CLI / Cursor / Cline / Continue | (your choice) |

The installer **will** verify these are present and tell you what's missing.

## Step 1 — Clone

```powershell
git clone --recursive https://github.com/Letenz/driver-harness-mcp.git
cd driver-harness-mcp
```

If you forgot `--recursive`:

```powershell
git submodule update --init --recursive
```

## Step 2 — Configure your guest VM

In the guest, open an **elevated** PowerShell and run:

```powershell
bcdedit /set testsigning on
bcdedit /debug on
# Restart the guest after this
```

Optional but recommended:
- Set the guest user to a known username/password (vmrun guest auth needs both)
- Install [VirtualKD-Redux's guest target driver](https://github.com/4d61726b/VirtualKD-Redux#installation) inside the guest

Then **create a baseline snapshot** named `test_mcp_ready` while the guest is in a clean booted state.
Every test cycle will revert to this snapshot.

See [`configure-guest-vm.md`](./configure-guest-vm.md) for full details.

## Step 3 — Run the installer (host, Administrator)

```powershell
# From the repo root, in an elevated PowerShell
powershell -ExecutionPolicy Bypass -File installer\install.ps1
```

The installer will:
1. Verify host prerequisites (VMware, VS, Python, Git)
2. Initialize and update submodules
3. Build the WinDbg extension (`windbgmcpExt.dll`) — or, if you skip this, fetch the prebuilt release
4. Set up Python virtual environments for the three MCP servers
5. Write the VirtualKD-Redux registry preset to `HKLM\Software\VirtualKD-Redux\Monitor`

After it finishes, run the doctor:

```powershell
powershell -ExecutionPolicy Bypass -File installer\doctor.ps1
```

You should see all green checkmarks.

## Step 4 — Configure VirtualKD-Redux

Open `vmmon64.exe` from your VirtualKD-Redux installation, verify:
- The **"Custom"** radio button is selected
- The custom command box matches `presets\registry\vkd-redux-monitor-template.reg`'s `CustomDebuggerTemplate` value

If anything looks off, see [`configure-vkd-redux.md`](./configure-vkd-redux.md).

## Step 5 — Configure your AI client

Pick one of the templates in [`presets/mcp-client-config/`](../presets/mcp-client-config/) and merge
it into your AI client's MCP configuration.

For Claude Code CLI:

```powershell
# Locations vary; consult the Claude Code CLI docs for the right path
# Typical: %APPDATA%\Claude\claude_code_settings.json (or similar)
```

See [`presets/mcp-client-config/claude-code-cli.json`](../presets/mcp-client-config/claude-code-cli.json)
for the exact JSON to paste.

## Step 6 — Run the first example

```powershell
cd examples\01-kernel-patch-bsod
.\run.ps1
```

This will:
1. Revert the guest to `test_mcp_ready` snapshot
2. Wait for VirtualKD + WinDbg + MCP extension to initialize
3. Send a `break_in` to the guest kernel
4. Patch a few bytes in `nt!SwapContext+5` to cause an exception on next thread switch
5. Continue execution → guest BSODs almost immediately
6. Run `!analyze -v` and print the result

If everything works you'll see something like:

```
BugCheck 0xA: IRQL_NOT_LESS_OR_EQUAL
...
BUCKET_ID:  AV_nt!SwapContext
```

🎉 Congrats. The full chain works.

## Step 7 — Let your AI take over

Now ask your AI assistant something like:

> "Use driver-harness-mcp to test a fresh BSOD, recover the VM, and report the BugCheck code."

If the Skills are loaded into context (see `skills/kernel-driver-testing/SKILL.md`),
the AI will know exactly which tools to call.

## Next steps

- Browse other [`examples/`](../examples/) (more coming in v0.2)
- Read the [Architecture](./architecture.md) doc to understand what's happening under the hood
- Hit a problem? [`troubleshooting.md`](./troubleshooting.md) has a flowchart of common failures
- Want to add new MCP tools? See `driver-harness-mcp/src/driver_harness_mcp/tools/` (TODO: contribution guide)
