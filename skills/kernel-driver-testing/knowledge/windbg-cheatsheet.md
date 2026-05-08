# WinDbg cheatsheet for AI use

Commands you'll actually need. Not exhaustive — refer to
[Microsoft docs](https://learn.microsoft.com/windows-hardware/drivers/debugger/) for the rest.

## Connection / target state

| Command | What it does | Notes |
|---|---|---|
| `vertarget` | Show target Windows version, kernel base, uptime | Healthy → fully connected |
| `.effmach` | Show effective machine (x64/arm64) | Sanity check |
| `g` | Continue execution | Returns target to running state |
| `gh` | Continue with exception handled | |
| `gn` | Continue with exception not handled | |
| `Ctrl+Break` (UI) | Break in | We use `BreakInHandler` from MCP |

## Process / thread inspection

| Command | What it does |
|---|---|
| `!process -1 0` | Brief info on current process |
| `!process 0 0` | Brief list of **all** processes (slow on large systems!) |
| `!process <addr> 7` | Detailed info on a specific process |
| `!thread` | Current thread |
| `!thread <addr>` | Specific thread |
| `!pcr` | Processor control region (current CPU) |
| `~` | **DO NOT USE in kernel mode** — different semantics |

## Symbols / modules

| Command | What it does |
|---|---|
| `lm` | List loaded modules |
| `lm m <pat>` | List modules matching pattern (`lm m nt`) |
| `lm v m <pat>` | Verbose: paths, version, PDB |
| `x <module>!<sym>` | Find symbol address (`x nt!NtCreateFile`) |
| `ln <addr>` | Nearest symbol to address |
| `.reload` | Force reload symbols |
| `.reload /f` | Force, even if already loaded |

## Memory inspection

| Command | What it does |
|---|---|
| `dq <addr> L<n>` | Dump qwords (64-bit values) |
| `dd <addr> L<n>` | Dump dwords |
| `db <addr> L<n>` | Dump bytes |
| `du <addr>` | Dump Unicode string |
| `da <addr>` | Dump ASCII string |
| `dt nt!_EPROCESS <addr>` | Dump structure |
| `!address <addr>` | What is this address (heap, stack, kernel, …) |

## Memory writes (BSOD-friendly!)

| Command | What it does | Risk |
|---|---|---|
| `eb <addr> <byte> [<byte>...]` | Write bytes | ⚠️ Patching kernel code = BSOD |
| `eq <addr> <qword>` | Write 64-bit value | ⚠️ |
| `ed <addr> <dword>` | Write 32-bit value | ⚠️ |

## Breakpoints

| Command | What it does |
|---|---|
| `bp <addr>` | Set breakpoint |
| `bu <module>!<sym>` | Unresolved breakpoint (sets when symbol resolves) |
| `bm <pat>` | Multi-breakpoint matching pattern |
| `ba <r/w/e><n> <addr>` | Hardware breakpoint (read/write/execute, size) |
| `bl` | List breakpoints |
| `bc *` | Clear all |
| `bd <id>` / `be <id>` | Disable / enable |

## Exceptions / events

| Command | What it does |
|---|---|
| `sxe ld:<driver.sys>` | Stop on driver load |
| `sx` | List exception filters |
| `.lastevent` | Last event |
| `.bugcheck` | Show BugCheck info if in BSOD state |

## Crash analysis

| Command | What it does |
|---|---|
| `!analyze -v` | The Big One. Always run after BSOD. |
| `!analyze -hang` | For hangs |
| `.dump /m <path>` | Save mini kernel dump |
| `.dump /f <path>` | Save full kernel dump (huge) |
| `kbn` | Stack with frame numbers |
| `.frame <n>` | Switch to frame |
| `dv` | Locals in current frame |

## Useful misc

| Command | What it does |
|---|---|
| `.cls` | Clear screen |
| `.echo <text>` | Print to output |
| `r <reg>` | Read register (`r rax`) |
| `r <reg>=<val>` | Write register |
| `?? <C++ expr>` | Evaluate C++-style expression with type info |
| `.help` / `.hh` | Open help |

## Things to avoid

- ❌ `.kill` / `q` — quits the debugger, you lose connection
- ❌ `.detach` in kernel mode — same
- ❌ Long-running `!for_each_thread` without need — slow
- ❌ Patching arbitrary kernel functions on a non-snapshotted VM — you'll need to revert anyway

## Output handling tips

- Some commands (notably `lm` with no filter, `!process 0 0`) produce **a lot** of output.
  WinDbg's MCP wrapper streams these but be patient — don't time out aggressively.
- Empty output usually means success for `bp`, `g`, `eb`, etc. The MCP layer
  whitelists these and converts to friendly messages.
