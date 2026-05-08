# Example 01 — Kernel-patch BSOD

The canonical smoke test. **If this works, your whole stack is healthy.**

## What it does

1. Reverts the guest VM to a clean snapshot (`test_mcp_ready` by default)
2. Waits for VKD + WinDbg + MCP extension to come up
3. Sends `break_in` to interrupt the running guest kernel
4. Reads the first few bytes of `nt!SwapContext` (a thread-context-switch routine called constantly)
5. Patches `nt!SwapContext+5` with `00 00 00 00 00` — this becomes `add [rax],al` which page-faults on the next context switch
6. Resumes the kernel with `g`
7. Within milliseconds, the kernel hits the bad bytes during a context switch → BSOD
8. Runs `!analyze -v` to confirm
9. Reverts the snapshot

## Expected output (paraphrased)

```
[+] Reverting to snapshot 'test_mcp_ready'...                 [OK,  ~1s]
[+] Starting VM...                                            [OK, ~10s]
[+] Waiting for windbgmcp pipe...                             [OK, ~15s]
[+] vertarget: Windows 10 Kernel Version 19041 ...
[+] break_in: GO -> BREAK                                     [~1s]
[+] x nt!SwapContext: fffff803`74205e90
[+] db nt!SwapContext L10: 48 8b c4 48 89 58 ...
[+] eb nt!SwapContext+5 00 00 00 00 00
[+] g (resume)
[+] BSOD detected within 1s
[+] !analyze -v output:
    BugCheck 0xA: IRQL_NOT_LESS_OR_EQUAL
    BUCKET_ID: AV_nt!SwapContext
[+] Reverting snapshot for cleanup...                         [OK]
[+] Done.
```

## Files

- `run.ps1` — driver script (PowerShell)
- `expected-output.txt` — sample of a successful run
- `pseudo-flow.md` — the same flow explained as if an AI were thinking through it

## Customizing

By default the script uses these values:
- VM name: `test_vm` (you'll need to edit if yours is different)
- Snapshot: `test_mcp_ready`
- Patch target: `nt!SwapContext+5`

If you have a snapshot with a different name, edit `run.ps1` and change `$Snapshot`.

## Why this exact technique?

`nt!SwapContext` is called every time the OS switches threads — many thousands of times per second.
Patching it guarantees the BSOD fires almost immediately, with no need to "trigger" anything from
userland. The exact patch (`00 00 00 00 00` at offset +5) creates a deterministic crash signature
(`AV_nt!SwapContext`) that's easy to verify.

## Don't do this on a real system

Patching kernel code is **not** a normal driver-testing technique. We use it here only because
it's a self-contained way to prove the harness can drive break/patch/resume/analyze.

For real driver testing, use `examples/03-driver-stress-test/` (planned for v0.2).

## What if it doesn't work?

Run the host-side doctor:

```powershell
powershell -ExecutionPolicy Bypass -File ..\..\installer\doctor.ps1
```

Then consult [`docs/troubleshooting.md`](../../docs/troubleshooting.md).
