# Workflow: First-time setup walkthrough

When the user says something like *"I just cloned this repo, help me get it running"*,
follow this script.

## Step 1 — Confirm prerequisites

Ask the user (don't guess):

> "Quick checklist before I help you set up:
> 1. Do you have **VMware Workstation Pro 16+** installed?
> 2. Do you have a **Windows 10/11 guest VM** ready, with admin access?
> 3. Do you have **Visual Studio 2022 + Windows SDK** installed (needed to build the WinDbg extension)?
>    - Or you're OK with using the prebuilt `windbgmcpExt.dll` from our GitHub release?
> 4. Do you have **Python 3.11+**?
> 5. Have you downloaded **VirtualKD-Redux** yet?
>
> If anything's missing, I'll point you to the download links."

## Step 2 — Run installer

Once they're ready, instruct:

```powershell
# Open an elevated PowerShell, in the repo root
powershell -ExecutionPolicy Bypass -File installer\install.ps1
```

If it fails, get the **exact error output** (not paraphrased) and consult
[`docs/troubleshooting.md`](../../../docs/troubleshooting.md) section A.

## Step 3 — Run doctor

```powershell
powershell -ExecutionPolicy Bypass -File installer\doctor.ps1
```

All checks should be green. Common red flags and fixes:
- ❌ `vmrun.exe not found` → user picked a non-default install path; set `$env:VMRUN_PATH`
- ❌ `windbgmcpExt.dll missing` → installer build step failed; rerun with `-SkipBuild` and use prebuilt
- ❌ `HKLM registry not configured` → installer needs admin and didn't get it; rerun elevated

After MCP servers are configured, prefer the structured tool check:

```text
driver-harness-mcp.diagnose_environment(check_guest=false)
```

## Step 3.5 — Create the per-user config

Before the guest-config step, make sure the user has their local
`driver-harness.config.json`. This is where VM path, snapshot name,
and guest credentials live.

```powershell
Copy-Item driver-harness.config.example.json driver-harness.config.json
```

Then ask the user for the **four values you cannot guess** and write
them into the file for them:

- `vm.vmx_path` — absolute path to the guest's `.vmx`
- `vm.baseline_snapshot` — the snapshot name to revert to (recommend `test_mcp_ready`;
  it may not exist yet — you'll create it in Step 4)
- `guest.admin_user` — guest admin username
- `guest.admin_password` — guest admin password. Prefer the
  `${env:DRIVER_HARNESS_GUEST_PASSWORD}` form and have them `$env:...`-set it
  in their shell, so the password doesn't sit in a file.

Leave `host.*` empty — you'll fill those in by checking explicit inputs,
environment variables, registry values, and fixed default install paths. Do not
scan whole drives or broad folders; ask the user if bounded probing fails.

## Step 4 — Configure the guest

Walk them through [`docs/configure-guest-vm.md`](../../../docs/configure-guest-vm.md). The essentials:
1. `bcdedit /debug on` and `/set testsigning on`
2. Install and configure VirtualKD-Redux target in the guest
3. Set a non-empty user password
4. Reboot, settle, **snapshot as `test_mcp_ready`**

Take this snapshot only after the guest really enters the VirtualKD-capable
boot configuration. The invariant is: reverting to `test_mcp_ready` should be
enough for the next boot to enter the VirtualKD two-machine debugging path once
host `vmmon64.exe` is running. A normal Windows snapshot taken before guest
VirtualKD setup is not a valid harness baseline. KDNET is an alternative only
when the VM is explicitly configured for KDNET.

## Step 5 — Configure VirtualKD-Redux on host

The installer should have written the registry already, but the user needs to
**launch `vmmon64.exe` from VKD's install dir** and confirm:
- "Custom" is selected
- The custom command box matches what's in `presets/registry/vkd-redux-monitor-template.reg`

If the path is not configured, ask the user for the full `vmmon64.exe` path
and write it to `host.vmmon64_path`. The AI can start/restart vmmon after that
path is known. For the smoothest closed loop, ask the user to run the current
agent/session as Administrator; otherwise registry repair and reliable vmmon
restart may need a manual elevated shell.

Do not accept `DebuggerType=3` here. MCP automation requires
`DebuggerType=2` (Custom), because `vmmon64.exe` uses this registry value to
decide how it auto-starts WinDbg. If it starts WinDbg through the non-custom
path, the `-c ".load ...; !mcpstart"` command is ignored and the pipe
`\\.\pipe\windbgmcp` never appears.

If changing the VKD registry, use this order:

1. Stop `vmmon64.exe`.
2. Write `DebuggerType=2` and the custom MCP template.
3. Start `vmmon64.exe`.
4. Revert/start the VM.

`vmmon64.exe` must be running before the VM restore/start event; otherwise it
does not observe VirtualKD and will not auto-launch WinDbg.

## Step 6 — Offer to register this repo with the current agent/client

After the installer, config, VirtualKD host setup, and `diagnose_environment`
are green, ask the user:

> "Do you want me to register the `kernel-driver-testing` skill and the
> required MCP servers (`driver-harness`, `windbg`, `vmware`) with your current
> AI agent/client now?"

Only proceed if the user confirms. If they say no, keep the repo usable through
manual docs and do not edit their agent/client config.

When they confirm:

- Register or copy `skills/kernel-driver-testing/` into the current agent's
  skill location, or point the agent at this repo's skill if the client supports
  repository-local skills.
- Pick the right MCP config from `presets/mcp-client-config/`:
  `claude-code-cli.json`, `claude-desktop.json`, or `cursor.json`.
- Replace `<REPO_ROOT>` with the absolute repo path.
- Preserve existing MCP entries and skill config. Merge/append only; never
  overwrite the whole client config.
- If the current agent/client config path is unknown, ask the user for it.
- If the agent/client requires restart/reload to discover new tools or skills,
  tell the user exactly that.

## Step 7 — Configure their AI client manually

Pick the right config from `presets/mcp-client-config/`:
- `claude-code-cli.json`
- `claude-desktop.json`
- `cursor.json`

Help them merge it into their existing client config (don't overwrite — append).

## Step 8 — Smoke test

First verify the structured status:

```text
driver-harness-mcp.diagnose_environment(check_guest=true)
driver-harness-mcp.start_vkd_monitor()
```

Then run the canonical example:

```powershell
cd examples\01-kernel-patch-bsod
.\run.ps1
```

Expected output (paraphrased): a BSOD `BugCheck 0xA: IRQL_NOT_LESS_OR_EQUAL` with
`BUCKET_ID: AV_nt!SwapContext`, then the VM is reverted clean.

If it works: 🎉 setup is complete, point them to other examples.

If it fails: walk them through troubleshooting. Don't keep retrying blindly.

## Step 9 — Hand-off

Once smoke test passes, tell the user:

> "Setup is verified working. From here you can:
> - Browse the other examples in `examples/`
> - Ask me to test your own driver — I'll need its `.sys` file path on the host
> - Look at `skills/kernel-driver-testing/SKILL.md` if you want to know what I can do
>
> Whenever you want to start a new test, ask me to '*run a test cycle*' or '*recover the VM and try X*'."
