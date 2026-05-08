# Workflow: Run a single driver test cycle

The bread-and-butter loop. **Every test starts and ends in the same clean state.**

## Pre-conditions

- Host has VMware Workstation Pro running
- Guest VM exists with snapshot `test_mcp_ready` (or whatever name the user uses — ask!)
- All three MCP servers are connected to your client
- Doctor script returns all green

If any of these are unclear, **ask the user first**. Don't assume.

## The 7-stage cycle

```
1. recover_to_clean_state   →  guest at known baseline
2. push_test_assets          →  copy driver / test program into guest
3. install_driver            →  sc create + sc start
4. trigger_event             →  cause whatever you're testing (load, BSOD, …)
5. capture_results           →  windbg !analyze, sc query, copy logs out
6. report                    →  summarize to user
7. revert (always)           →  back to step 0 for next cycle
```

## Stage details

### 1. recover_to_clean_state

Use the `driver-harness-mcp` tool of the same name. It encapsulates:
- `vmrun revertToSnapshot <vmx> <snapshot_name>` (works regardless of VM state)
- `vmrun start <vmx> nogui` if not already running
- Polls `vmrun checkToolsState` until "running"
- Optionally waits for `\\.\pipe\windbgmcp` and a healthy `vertarget`

Expect ~25 seconds total.

### 2. push_test_assets

Use `vmware-mcp.vmrun_copy_to`:
- Source: host file path (where you built/downloaded the driver)
- Destination: guest path, typically `C:\Users\<user>\Desktop\<driver>.sys`
- Verify with `vmrun_file_exists`

### 3. install_driver

Two `vmrun_run` calls:
```powershell
sc create MyDrv type= kernel start= demand binPath= "C:\path\to\driver.sys"
sc start MyDrv
```

If `sc start` causes BSOD, that's a result you record — go straight to stage 5.
The harness should detect BSOD via WinDbg `BUGCHECK` event or the absence of guest response.

### 4. trigger_event

Depends on what you're testing. Common patterns:
- **Load-time test:** stage 3 already loaded; nothing to trigger.
- **IOCTL-based test:** push a userland test exe, run it; it does `DeviceIoControl`.
- **Kernel patch BSOD:** use `windbg-ext-mcp.break_in` + `eb` to corrupt a critical function.

### 5. capture_results

If a BSOD occurred:
```
break_in (if not already broken)
.bugcheck      → BugCheck code
!analyze -v    → full analysis
.dumpdebug     → pointers
```

If no BSOD:
- `sc query MyDrv` → state and exit code
- Pull logs (DbgView, ETW) via `vmrun_copy_from`

### 6. report

Tell the user, in this order:
1. Whether it crashed (and the BugCheck code if so)
2. The bucket from `!analyze -v` (e.g. `BUCKET_ID: AV_nt!SomeFunc`)
3. Brief interpretation (likely cause: NULL deref, use-after-free, etc.)
4. Where the dump / logs were saved (host paths)

### 7. revert (always)

Even if the test passed. Keeps subsequent cycles clean.

## Idempotency

The whole cycle should be safe to retry. If something goes wrong mid-way:
- Stop where you are
- Tell the user
- **Always revert** before suggesting "let's try again"

## Example: one full cycle in pseudocode

```python
state = harness.recover_to_clean_state(vm="test_vm", snapshot="test_mcp_ready")
if not state.ok:
    return user_error(state.message)

vmware.vmrun_copy_to(host="C:/build/mydriver.sys",
                    guest="C:/Users/test/Desktop/mydriver.sys")

result = vmware.vmrun_run("sc create MyDrv ...")
result = vmware.vmrun_run("sc start MyDrv")

if windbg.is_target_broken():
    # BSOD occurred during sc start
    bugcheck = windbg.execute_command(".bugcheck")
    analysis = windbg.execute_command("!analyze -v")
    report_to_user(bugcheck, analysis)
else:
    state = vmware.vmrun_run("sc query MyDrv")
    report_to_user(state)

harness.recover_to_clean_state(vm="test_vm", snapshot="test_mcp_ready")  # always
```
