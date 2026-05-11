# Quickstart — 30 minutes to your first AI-driven BSOD

This guide takes you from "fresh Windows host" to "AI assistant runs an end-to-end
kernel-patch BSOD test" in about 30 minutes.

## Prerequisites

You need to install these **manually** (the installer won't do it):

| Component | Why | Required? | Download |
|---|---|---|---|
| **VMware Workstation Pro 16+** | Hosts the guest VM | required | [vmware.com](https://www.vmware.com/products/workstation-pro.html) |
| **A Windows guest VM** | Target for kernel debugging. Win10 19041+ or Win11 recommended. | required | (your install media) |
| **Windows SDK / Debugging Tools for Windows** | Provides WinDbg Preview (`DbgX.Shell.exe`), debug symbols | required | [docs.microsoft.com](https://learn.microsoft.com/windows-hardware/drivers/debugger/) |
| **Python 3.11+** | For the MCP servers | required | [python.org](https://www.python.org/) |
| **Git for Windows** | To clone with submodules | required | [git-scm.com](https://git-scm.com/) |
| **VirtualKD-Redux 2024.3** | Fast virtual KD transport | required | [github.com/4d61726b/VirtualKD-Redux/releases](https://github.com/4d61726b/VirtualKD-Redux/releases) |
| **An MCP-capable AI client** | Claude Code CLI / Cursor / Cline / Continue | required | (your choice) |
| **Visual Studio 2022 + C++ workload** | Only if you want to rebuild `windbgmcpExt.dll` from source. The repo ships a precompiled DLL in `bin/`. | **optional** | [visualstudio.microsoft.com](https://visualstudio.microsoft.com/) |

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

The default path uses the precompiled `bin\windbgmcpExt.dll` so you do **not** need
Visual Studio installed:

```powershell
# From the repo root, in an elevated PowerShell
powershell -ExecutionPolicy Bypass -File installer\install.ps1
```

If you want to compile the extension from source instead (requires VS 2022 + C++
workload + Windows 10 SDK):

```powershell
powershell -ExecutionPolicy Bypass -File installer\install.ps1 -Build
```

The installer will:
1. Verify host prerequisites (VMware, Python, Git, WinDbg Preview, VirtualKD-Redux)
2. Initialize and update submodules under `third_party\`
3. Install the WinDbg extension DLL into `%ProgramData%\driver-harness-mcp\bin\`
   (either by copying from `bin\windbgmcpExt.dll` after a SHA-256 integrity check,
   or by compiling `third_party\windbg-ext-mcp\extension\` if you passed `-Build`)
4. Set up Python virtual environments for the MCP servers
5. Write the VirtualKD-Redux registry preset to
   `HKLM\Software\VirtualKD-Redux\Monitor` so that VKD auto-launches WinDbg
   Preview with our extension pre-loaded

After it finishes, run the doctor:

```powershell
powershell -ExecutionPolicy Bypass -File installer\doctor.ps1
```

You should see all green checkmarks.

### Step 3.5 — Create your per-user config

Copy the example file to its real name (gitignored) and fill in the
values your AI cannot guess:

```powershell
Copy-Item driver-harness.config.example.json driver-harness.config.json
```

Then edit `driver-harness.config.json`. The minimum fields you must
fill in:

- `vm.vmx_path` — absolute path to your guest's `.vmx` file
- `vm.baseline_snapshot` — name of the snapshot to revert to (e.g. `test_mcp_ready`)
- `guest.admin_user` / `guest.admin_password` — guest admin credentials

You can also leave `host.vmrun_path` / `host.vmmon64_path` empty and
let your AI assistant fill them in by probing your filesystem.

> 💡 **Don't worry about getting it perfect right now.** The
> [`setup-from-scratch.md`](../skills/kernel-driver-testing/workflows/setup-from-scratch.md)
> workflow describes how an AI walks a user through this in chat.

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

## Next steps

- Browse other [`examples/`](../examples/) (more coming in v0.2)
- Read the [Architecture](./architecture.md) doc to understand what's happening under the hood
- Hit a problem? [`troubleshooting.md`](./troubleshooting.md) covers the common failures
