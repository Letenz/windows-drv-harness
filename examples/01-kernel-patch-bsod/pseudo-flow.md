# Example 01 — as an AI would think through it

Here's how an AI assistant equipped with this repo's Skills and MCP servers
might reason through this example. Shown here so **you can spot if your AI
is doing something different and why**.

---

**User:** Run a kernel-patch BSOD smoke test on my VM at `D:\VMs\test_win10.vmx`.

**AI (reasoning):**

> The user wants the smoke test from `examples/01-kernel-patch-bsod`. I know from
> `skills/kernel-driver-testing/SKILL.md` that the canonical 7-stage cycle is:
> recover → deploy → trigger → capture → report → revert. This example skips
> "deploy" (no driver needed; we patch `nt` directly).
>
> Plan:
> 1. `driver_harness.recover_to_clean_state(vmx=..., snapshot='test_mcp_ready')` — bring VM up to known baseline
> 2. `windbg.execute_command('vertarget')` — health check
> 3. `windbg.break_in()` — we need broken state for `eb` (from common-pitfalls: P-W1)
> 4. `windbg.execute_command('x nt!SwapContext')` — find address, parse output
> 5. `windbg.execute_command('db nt!SwapContext L10')` — snapshot bytes for reporting
> 6. `windbg.execute_command('eb nt!SwapContext+5 00 00 00 00 00')` — patch
> 7. `windbg.execute_command('g')` — resume; BSOD within ms
> 8. `windbg.execute_command('!analyze -v')` — crash analysis
> 9. Parse `BUGCHECK_CODE` and `BUCKET_ID` from output
> 10. `driver_harness.recover_to_clean_state(...)` — always revert
>
> Before step 1, confirm with user since this is destructive.

**AI (to user):**

> I'll run the kernel-patch BSOD test. This will:
> - Revert your VM at `D:\VMs\test_win10.vmx` to snapshot `test_mcp_ready`
> - Trigger a BSOD by patching `nt!SwapContext+5`
> - Analyze the crash with `!analyze -v`
> - Revert again to clean up
>
> Proceed?

**User:** Yes.

**AI:**

```
Calling: driver_harness.recover_to_clean_state(
    vmx_path="D:\\VMs\\test_win10.vmx",
    snapshot_name="test_mcp_ready"
)
→ ok=true, elapsed=24.3s, message="VM reverted, started, and \\.\pipe\windbgmcp ready."

Calling: windbg.execute_command(command="vertarget")
→ "Windows 10 Kernel Version 19041 MP (2 procs) Free x64"

Calling: windbg.break_in(timeout_ms=5000)
→ ok=true, state_before=GO, state_after=BREAK

Calling: windbg.execute_command(command="x nt!SwapContext")
→ "fffff803`74205e90 nt!SwapContext ..."
Parsed address: fffff803`74205e90

Calling: windbg.execute_command(command="db nt!SwapContext L10")
→ "fffff803`74205e90  48 8b c4 48 89 58 08 48..."

Calling: windbg.execute_command(command="eb nt!SwapContext+5 00 00 00 00 00")
→ success (write confirmed)

Calling: windbg.execute_command(command="g", timeout_ms=2000)
→ returns quickly — target hit a fault; we're back in BREAK state

Calling: windbg.execute_command(command="!analyze -v", timeout_ms=30000)
→ full output, parsed:
  BUGCHECK_CODE: 0xA (IRQL_NOT_LESS_OR_EQUAL)
  FAILED_INSTRUCTION_ADDRESS: nt!SwapContext+0x5
  BUCKET_ID: AV_nt!SwapContext

Calling: driver_harness.recover_to_clean_state(same args)
→ ok=true, elapsed=22.1s
```

**AI (to user):**

> ✅ Smoke test successful.
>
> - **BugCheck:** `0xA IRQL_NOT_LESS_OR_EQUAL`
> - **Bucket:** `AV_nt!SwapContext`
> - **Faulting RIP:** `nt!SwapContext+0x5` (as expected — that's where we patched)
>
> The guest kernel reached the patched bytes during a thread-context switch and
> page-faulted. Full stack and `!analyze -v` output attached.
>
> VM was reverted successfully. Whole cycle took ~50 seconds.
>
> Your driver-harness-mcp stack is healthy end-to-end.

---

## What to check if your AI does something different

- If it skips `break_in`, it'll hit `Kernel transport in use, packet write failed` on step 6. Common.
- If it tries to `stop` the VM after BSOD (instead of `revertToSnapshot`), that won't work reliably. The SKILL says: prefer revert.
- If it doesn't revert at the end, nag it. Next test would start from a patched kernel.
