# Workflow: Crash analysis

You hit a BSOD. Now what?

## Stage 0 — Verify you're broken-in

Before doing **any** crash analysis you must confirm WinDbg is in **broken** state.
Signals that you're broken:
- `r rip` returns a register value (not error 0x80040205)
- `vertarget` returns full output without the "Kernel transport in use" suffix
- `g` would resume execution if issued

If the target is running and you got a BSOD elsewhere, call `break_in` first.
If `break_in` itself fails, the kernel may be already broken on its own (BugCheck halts the kernel) —
just try `vertarget` directly.

## Stage 1 — Get the BugCheck code

```
.bugcheck
```

This shows e.g. `Bugcheck code 0000000A` (`IRQL_NOT_LESS_OR_EQUAL`). Look up
the code in [`knowledge/common-bugcheck-codes.md`](../knowledge/common-bugcheck-codes.md).

## Stage 2 — Run !analyze -v

```
!analyze -v
```

This does **a lot** of work. It will produce:

- `BUCKET_ID:` — Microsoft's hash of the failure (e.g. `AV_nt!SwapContext`). Two crashes with the same bucket are usually the same bug.
- `STACK_TEXT:` — The call stack at crash time. Read top-down.
- `MODULE_NAME:` — Which module faulted (`nt`, `your_driver`, `ntoskrnl`, etc.)
- `IMAGE_NAME:` — Filename version of the above
- `FAILURE_BUCKET_ID:` — Less detailed version of `BUCKET_ID`
- `OSNAME / OSVERSION` — For correlating across builds

## Stage 3 — Read the stack

The stack frames go from current (top) to oldest (bottom). Look for:
- Your driver's name in any frame → it's in your code path
- Standard kernel functions (`KiPageFault`, `KeBugCheckEx`, `RtlpBreakWithStatusInstruction`) — these are
  symptoms, not causes. Look at the frame **below** them.

## Stage 4 — Identify the immediate cause

Patterns and what they usually mean:

| Symptom in `!analyze -v` | Likely root cause |
|---|---|
| `Attempt to write to read-only memory: 0xfffffXXX...` | Driver wrote to a kernel page, possibly corrupted PFN |
| `IRQL_NOT_LESS_OR_EQUAL` + STACK has paged code | Touched paged memory at DISPATCH_LEVEL or higher |
| `KMODE_EXCEPTION_NOT_HANDLED` + `c0000005` | Access violation in kernel mode |
| `SYSTEM_SERVICE_EXCEPTION` | Crash during a system call entry/exit path |
| `BAD_POOL_HEADER` / `BAD_POOL_CALLER` | ExAllocatePool/ExFreePool misuse, double-free, header overrun |
| `DRIVER_VERIFIER_DETECTED_VIOLATION` | DV caught a known bad pattern; the line ID tells you which |

## Stage 5 — Correlate with source

If you have the source for the faulting driver (and PDBs):
```
.reload                           # ensure symbols loaded
ln @rip                           # nearest symbol to the faulting RIP
u @rip-10 L20                     # disassemble around the fault
.frame N                          # switch to a stack frame
dv                                # local variables in that frame
dt nt!_FOO ptr                    # dump structure
```

## Stage 6 — Save artifacts

- `.dump /m C:\dumps\test1.dmp` (small kernel dump) — for offline review
- Copy any logs from the guest before reverting:
  - `C:\Windows\MEMORY.DMP` (if `DebugInfoType=2`)
  - `C:\Windows\Minidump\*.dmp`
  - DbgView .log if you had it running

> ⚠️ **Always copy artifacts out BEFORE you revert the snapshot.** Revert wipes everything.

## Stage 7 — Decide: revert or continue investigating?

Default: **revert**. The kernel is in an undefined post-bugcheck state — even
though WinDbg lets you continue (`g`), behavior is unpredictable.

Exceptions where you might **not** revert immediately:
- You're in active debugging mid-investigation; you'll revert later
- You want to look at related kernel structures while the snapshot of memory is intact

If you stay, set a hard time limit (15 min?) and revert after.

## Reporting to the user

Always include, in this order:
1. **What crashed** — BugCheck code + name (e.g. `0xA IRQL_NOT_LESS_OR_EQUAL`)
2. **Where** — top stack frame, module name
3. **Bucket ID** — for grouping with other crashes
4. **Likely cause** — your interpretation in plain English
5. **Where artifacts are** — dump path, log paths
6. **Suggested next step** — fix, reproduce, escalate, etc.
