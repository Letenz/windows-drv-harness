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

## Standard workflows

See [`workflows/`](./workflows/) for full versions. Summary:

1. **[`setup-from-scratch.md`](./workflows/setup-from-scratch.md)** — User just installed the repo. Walk them through guest configuration and baseline snapshot creation.
2. **[`run-test-cycle.md`](./workflows/run-test-cycle.md)** — Revert → deploy driver → trigger → analyze → revert. The daily bread-and-butter.
3. **[`crash-analysis.md`](./workflows/crash-analysis.md)** — How to read `!analyze -v` output, identify bucket IDs, correlate with driver code.

## What NOT to do

- ❌ **Don't `.crash` while the target is running.** You'll get `Kernel transport in use, packet write failed`. Always `break_in` first.
- ❌ **Don't forget to revert after a BSOD.** The guest is in a corrupted state; future tests will be unreliable.
- ❌ **Don't try to `stop` a BSODed VM with `vmrun stop`**. Use `vmrun reset hard` or just `revertToSnapshot` (which works from any state).
- ❌ **Don't hardcode IPs, usernames, or paths** in scripts you generate for the user. Ask or read config.
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
