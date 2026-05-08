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

## Step 4 — Configure the guest

Walk them through [`docs/configure-guest-vm.md`](../../../docs/configure-guest-vm.md). The essentials:
1. `bcdedit /debug on` and `/set testsigning on`
2. Install VirtualKD-Redux target in the guest
3. Set a non-empty user password
4. Reboot, settle, **snapshot as `test_mcp_ready`**

## Step 5 — Configure VirtualKD-Redux on host

The installer should have written the registry already, but the user needs to
**launch `vmmon64.exe` from VKD's install dir** and confirm:
- "Custom" is selected
- The custom command box matches what's in `presets/registry/vkd-redux-monitor-template.reg`

## Step 6 — Configure their AI client

Pick the right config from `presets/mcp-client-config/`:
- `claude-code-cli.json`
- `claude-desktop.json`
- `cursor.json`

Help them merge it into their existing client config (don't overwrite — append).

## Step 7 — Smoke test

Run the canonical example:

```powershell
cd examples\01-kernel-patch-bsod
.\run.ps1
```

Expected output (paraphrased): a BSOD `BugCheck 0xA: IRQL_NOT_LESS_OR_EQUAL` with
`BUCKET_ID: AV_nt!SwapContext`, then the VM is reverted clean.

If it works: 🎉 setup is complete, point them to other examples.

If it fails: walk them through troubleshooting. Don't keep retrying blindly.

## Step 8 — Hand-off

Once smoke test passes, tell the user:

> "Setup is verified working. From here you can:
> - Browse the other examples in `examples/`
> - Ask me to test your own driver — I'll need its `.sys` file path on the host
> - Look at `skills/kernel-driver-testing/SKILL.md` if you want to know what I can do
>
> Whenever you want to start a new test, ask me to '*run a test cycle*' or '*recover the VM and try X*'."
