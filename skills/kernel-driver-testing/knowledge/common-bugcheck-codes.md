# Common BugCheck codes

Reference for quick interpretation. Full list:
[Microsoft docs](https://learn.microsoft.com/windows-hardware/drivers/debugger/bug-check-code-reference2).

## Top 10 you'll see in driver testing

| Code | Name | What it means | Common cause |
|---|---|---|---|
| `0x0A` | `IRQL_NOT_LESS_OR_EQUAL` | Touched paged memory at IRQL >= DISPATCH_LEVEL | Spinlock held while accessing pageable code/data |
| `0x1E` | `KMODE_EXCEPTION_NOT_HANDLED` | Unhandled CPU exception in kernel mode | NULL deref, divide by zero, bad pointer |
| `0x3B` | `SYSTEM_SERVICE_EXCEPTION` | Crash during a syscall handler path | Bad pointer in syscall, hook gone wrong |
| `0x50` | `PAGE_FAULT_IN_NONPAGED_AREA` | Reference to a page that shouldn't be paged | Use-after-free, dangling pointer |
| `0x7E` | `SYSTEM_THREAD_EXCEPTION_NOT_HANDLED` | Like 0x1E but in a system thread | Same root causes |
| `0x7F` | `UNEXPECTED_KERNEL_MODE_TRAP` | CPU trap (double fault, invalid opcode, etc.) | Stack overflow, bad assembly, corrupted IDT |
| `0xC1` | `SPECIAL_POOL_DETECTED_MEMORY_CORRUPTION` | Driver Verifier caught pool corruption | Buffer over/underrun |
| `0xC4` | `DRIVER_VERIFIER_DETECTED_VIOLATION` | DV caught a known bad pattern | Many sub-codes; check `arg1` |
| `0xCA` | `PNP_DETECTED_FATAL_ERROR` | PnP manager caught a driver doing wrong thing | IRQL violations in PnP IRPs |
| `0xE2` | `MANUALLY_INITIATED_CRASH` | Someone called `KeBugCheck` voluntarily | Test triggers, `Ctrl+ScrollLock+ScrollLock`, `.crash` |

## Reading `!analyze -v` for these

For each crash, `!analyze -v` shows:

```
BUGCHECK_CODE: 0xa
BUGCHECK_P1: <addr referenced>
BUGCHECK_P2: <IRQL when ref'd>
BUGCHECK_P3: <0=read, 1=write, 8=execute>
BUGCHECK_P4: <RIP that referenced it>
```

For `0x0A`:
- `P1` = the address that was accessed
- `P2` = the IRQL at that time
- `P3` = whether read/write/execute
- `P4` = where the access came from

So `0xA P1=00000000`00000000 P2=2 P3=0 P4=fffff80...` means: NULL read at DISPATCH_LEVEL,
faulting RIP is in `nt!something` at `P4`.

## DV-caught violations (`0xC4`)

The `arg1` of `0xC4` tells you which DV check fired. Common ones:

| arg1 | Meaning |
|---|---|
| `0x00` | DV detected pool tag overrun |
| `0x21` | Driver leaked memory at unload |
| `0x91` | Driver in IRQL violation (called function at wrong IRQL) |
| `0xF6` | Tried to free pool from wrong IRQL |
| `0x101` | DV's I/O verifier detected violation |

Full list in `wdm.h` under `DRIVER_VERIFIER_DETECTED_VIOLATION` constants, or
[here](https://learn.microsoft.com/windows-hardware/drivers/debugger/bug-check-0xc4--driver-verifier-detected-violation).

## Suspect patterns

| Faulting RIP in… | Likely culprit |
|---|---|
| `nt!ExFreePoolWithTag` | Double-free, corrupt pool header |
| `nt!Mm*` | Memory manager — usually corrupt page tables, bad PFN |
| `nt!Ki*` | Kernel internals — often paging or interrupt-related |
| `<your_driver>` | Bug in your code 🙂 |
| `nt!SwapContext` | Sometimes "real" SwapContext bug, often caused by stack/PCR corruption from your driver |
| `Ntfs.sys` / `FltMgr.sys` | Filesystem filter driver issue |

## When `!analyze -v` is wrong

`!analyze` uses heuristics. It's usually right but **always sanity-check the stack**:

```
kbn               # stack with frame numbers
.frame N          # zoom into a frame
dv                # locals
u @rip-10 L20     # disassemble where it crashed
```

If the bucket says your driver but the actual crash is in `nt!`, look at frames below — your
driver may have **set up** a corrupt state that triggered the crash later.
