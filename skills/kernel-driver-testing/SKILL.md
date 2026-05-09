---
name: kernel-driver-testing
description: |
  End-to-end automation of Windows kernel driver testing with VMware, VirtualKD-Redux,
  and WinDbg Preview, wired together via MCP (Model Context Protocol) servers.
  Load this when asked to deploy drivers, trigger BSODs, analyze crash dumps,
  or otherwise orchestrate kernel debugging workflows in a controlled VM.
version: 0.1.0
requires:
  mcp_servers:
    - vmware-mcp
    - windbg-ext-mcp
    - driver-harness-mcp
---

# Kernel Driver Testing Skill

You are equipped to drive a complete Windows kernel debugging environment end-to-end.
This skill document gives you the mental model, standard workflows, and common
pitfalls you need.

## Mental model

Three MCP servers, layered by abstraction:

```
 You (the AI)
     │
     ▼
┌──────────────────────────────────────────────────────────┐
│ driver-harness-mcp  (high-level: recover/test_cycle)     │
├──────────────────────────────────────────────────────────┤
│ windbg-ext-mcp      (WinDbg control — break_in, execute, │
│                      .crash, !analyze, lm, bp, eb, ...)  │
├──────────────────────────────────────────────────────────┤
│ vmware-mcp          (VM control — snapshot, start, stop, │
│                      push/pull files, run programs)      │
└──────────────────────────────────────────────────────────┘
```

**Rule of thumb:** prefer the **highest-level tool** that does what you need.
If `driver-harness-mcp` has `recover_to_clean_state`, use it instead of
orchestrating `vmware-mcp` primitives yourself.

## Reading user config

At the start of any session involving the harness, read
`driver-harness.config.json` in the repo root. It contains values only
the user knows (VM path, snapshot name, guest credentials, tool
locations). All inline comments and field docs live in
`driver-harness.config.example.json` — read that too if the schema
isn't obvious.

Rules:

- **If `driver-harness.config.json` is missing**, tell the user to
  `Copy-Item driver-harness.config.example.json driver-harness.config.json`
  and fill in at least: `vm.vmx_path`, `vm.baseline_snapshot`,
  `guest.admin_user`, `guest.admin_password`. Do not proceed with any
  VM or harness operation until these exist.
- **If a field value is `"${env:VAR_NAME}"`**, resolve it from the
  process's environment. If the env var is missing, ask the user to
  set it (e.g. `$env:DRIVER_HARNESS_GUEST_PASSWORD = '...'`) rather
  than prompting them to paste the password into chat.
- **If `host.vmrun_path` / `host.vmmon64_path` are empty**, it's fine
  to probe the filesystem yourself (`Get-ChildItem -Recurse` on likely
  drives, registry under `HKLM:\Software\VMware, Inc.\VMware Workstation`,
  etc.). Found something? **Offer the path to the user for confirmation,
  then write it back into the config.**
- **Never guess** `vm.*` or `guest.*` values. Ask.

Destructive-operation guard: do not run `revertToSnapshot`, edit the
VKD registry, delete a venv, patch kernel memory, or trigger a BSOD
until the config has valid `vm.vmx_path`, `vm.baseline_snapshot`, and
`guest.admin_user`/`admin_password`. These three are what lets you
roll back; without them, a bad run leaves the guest in an unknown
state.

## Standard workflows

See [`workflows/`](./workflows/) for full versions. Summary:

1. **[`setup-from-scratch.md`](./workflows/setup-from-scratch.md)** — User just installed the repo. Walk them through guest configuration and baseline snapshot creation.
2. **[`run-test-cycle.md`](./workflows/run-test-cycle.md)** — Revert → deploy driver → trigger → analyze → revert. The daily bread-and-butter.
3. **[`crash-analysis.md`](./workflows/crash-analysis.md)** — How to read `!analyze -v` output, identify bucket IDs, correlate with driver code.

## What NOT to do

- ❌ **Don't `.crash` while the target is running.** You'll get `Kernel transport in use, packet write failed`. Always `break_in` first.
- ❌ **Don't forget to revert after a BSOD.** The guest is in a corrupted state; future tests will be unreliable.
- ❌ **Don't try to `stop` a BSODed VM with `vmrun stop`**. Use `vmrun reset hard` or just `revertToSnapshot` (which works from any state).
- ❌ **Don't hardcode IPs, usernames, or paths** in scripts you generate for the user. Read them from `driver-harness.config.json`, or ask.
- ❌ **Don't bypass the user's approval** for destructive actions (revert, reset, kernel patch). Describe, then confirm.

## Common pitfalls — short version

Full list in [`knowledge/common-pitfalls.md`](./knowledge/common-pitfalls.md).

| Signal | Probable cause |
|---|---|
| MCP tool returns `Access is denied (5)` on pipe | SDDL patch missing — confirm you're using `Letenz/windbg-ext-mcp` |
| `execute_command` returns partial output and stalls | Target is running, need `break_in` first |
| `vmrun start` succeeds but `\\.\pipe\kd_<vm>` never appears | Guest isn't booting into the debug entry (VKD entry), or bcdedit debug is off |
| WinDbg launches but `\\.\pipe\windbgmcp` missing | `-c .load` didn't run — check `DebuggerType=2` and `CustomDebuggerTemplate` |
| `vmrun -gu/-gp` says "Command requires valid user name and password" | Guest account has empty password; vmrun rejects that |

## When in doubt

- Call `driver-harness-mcp.wait_mcp_ready()` to confirm the whole stack is up
- Run `execute_command("vertarget")` — if it returns a Windows kernel version string, everything's healthy
- Read [`knowledge/windbg-cheatsheet.md`](./knowledge/windbg-cheatsheet.md) before guessing commands

## Escalation

If a workflow fails in a way these docs don't cover:

1. Summarize what you tried and the exact error
2. Suggest the user run `installer\doctor.ps1`
3. Point them to `docs/troubleshooting.md`

Do **not** attempt random recovery actions (killing processes, rebooting, etc.) without explicit user approval.
