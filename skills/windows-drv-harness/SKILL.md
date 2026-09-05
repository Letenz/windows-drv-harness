---
name: windows-drv-harness
description: Build and test Windows kernel drivers in user-owned VMware labs through target-scoped VirtualKD/WinDbg sessions. Use for driver build, deploy, load/unload, BSOD analysis, snapshot reset, lab setup, or concurrent testing across configured VMs.
---

# Windows Driver Harness

Use the high-level `windows-drv-harness` MCP tools. They hide VMware,
VirtualKD, WinDbg startup, credentials, and cleanup from the model. Do not
reimplement that orchestration with ad-hoc shell commands while these tools
are available.

## Normal Flow

1. If the target is not explicit, call `lab_list_targets` and use the default
   target or ask the user to choose.
2. Call `lab_doctor(target)`. Continue only when it returns `status=ready`.
3. Call `driver_build(solution_path)`. Use the returned absolute `sys_path`.
4. Call `driver_test(target, sys_path, service_name, expect)`.
5. Read `status`, `passed`, evidence, and `next_action`; do not infer success
   from a window, screenshot, or process alone.

`driver_test` owns the whole VM test cycle and always attempts to restore the
target's baseline before returning.

For an intentionally crashing sample:

```text
driver_build -> driver_test(expect="crash") -> inspect crash evidence ->
patch the smallest source area -> driver_build ->
driver_test(expect="success")
```

A successful crash run must contain a WinDbg bugcheck and probable culprit.
A successful fixed run must show service create/start/stop/delete, module load
and unload evidence, and `cleanup.status=reverted`.

## Tool Choice

- `lab_list_targets`: discover configured profile names without exposing
  credentials.
- `lab_doctor`: read-only readiness check. Follow its `failed_checks` and
  `next_action` exactly.
- `lab_start`: open an interactive target-scoped WinDbg session. Ordinary
  build/test loops can skip this because `driver_test` starts the lab itself.
- `driver_build`: select an MSBuild compatible with the installed WDK and
  return the generated `.sys` path.
- `driver_test`: deploy and exercise a driver, collect debugger evidence, and
  reset the VM.
- `debug_run`: run one targeted WinDbg command only when `driver_test`
  evidence is insufficient.
- `lab_reset`: restore only the selected target after an interrupted or
  interactive session.

Do not call `debug_run` for routine load/unload checks already implemented by
`driver_test`.

## Configuration

The active config is machine-local, not part of the skill:

```text
%LOCALAPPDATA%\windows-drv-harness\config.json
```

`WINDOWS_DRV_HARNESS_CONFIG` may override that path. Config version 2 keeps
shared host tools under `host` and any number of VM profiles under `targets`.
Every target binds four user-confirmed values:

```text
vmx_path             absolute .vmx path
baseline_snapshot    snapshot saved after a verified WinDbg attach
kd_pipe              that VM's stable VirtualKD main pipe
mcp_pipe             unique windbg-mcp endpoint for this target
```

Guest credentials are target-specific. They may be plaintext in this local
file or `${env:VAR_NAME}`. Never print or commit them.

To add or update a target, run `scripts/configure_target.py`; it prompts for
the password without putting it on the command line. Then run
`scripts/setup-host.ps1`. That script self-elevates when required, configures
VirtualKD for harness-managed WinDbg, records bounded-discovery tool paths,
and ensures one global `vmmon64.exe` process.

## MCP Setup

First inspect the tools already exposed by the current agent. If the seven
tools above are visible, use them directly.

If they are missing:

```powershell
powershell -ExecutionPolicy Bypass -File <SKILL_DIR>\scripts\install-mcp.ps1
powershell -ExecutionPolicy Bypass -File <SKILL_DIR>\scripts\detect-mcp.ps1
```

Register only after the user authorizes changing the current MCP client:

```powershell
powershell -ExecutionPolicy Bypass -File <SKILL_DIR>\scripts\register-mcp.ps1 -Apply
```

The client receives one high-level server named `windows-drv-harness`, not a
large set of raw VMware tools.

## Invariants

- Operate only the requested target. Never choose a VM from `vmrun list`.
- Do not scan drives for VMX files, snapshots, credentials, or tools.
- A baseline is valid only when saved after the guest booted and classic
  WinDbg successfully attached through VirtualKD/KDNET.
- Each target needs a unique `mcp_pipe`. Multiple target sessions may run in
  parallel; startup is briefly serialized so VirtualKD pipe ownership remains
  unambiguous.
- `vmmon64.exe` is host-global. Configure/restart it during host setup, not at
  the beginning of every target session.
- Never close another target's WinDbg or restore another target's snapshot.
- On a failed gate, follow `next_action` and retry once after a concrete fix.
  If the same gate remains blocked, report it instead of improvising.
- Never expose passwords, API keys, tokens, or unredacted local config.

## Manual Recovery

Read [references/detailed-runbook.md](references/detailed-runbook.md) only to
diagnose the harness itself, recover an interrupted target, or use the raw
windbg-mcp endpoint. Normal driver tasks should not load it.

## Report

Return the selected target, build result, test status, key WinDbg evidence,
and final cleanup state. Keep command logs on disk and return their path rather
than pasting large raw output.
