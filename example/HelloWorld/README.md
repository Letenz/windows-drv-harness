# HelloWorld Crash/Fix Example

Minimal WDM kernel driver used to test the full `windows-drv-harness`
build-test-debug-fix loop.

This example is intentionally broken. `DriverEntry` writes through a `NULL`
pointer, so the first load should crash the guest. The point is to prove that
an AI agent can deploy the driver to VMware, catch and analyze the BSOD through
WinDbg MCP, patch the source, rebuild, and retest the fixed driver.

## Build

Use a Visual Studio + WDK command prompt, or point MSBuild at the solution:

```powershell
& "C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\MSBuild\Current\Bin\MSBuild.exe" `
  .\HelloWorld.sln /p:Configuration=Debug /p:Platform=x64
```

If your WDK is installed with VS2022 tasks, use the VS2022 MSBuild path
instead. The real harness test that inspired this example required VS2019
MSBuild because that machine had the WDK v16 build tasks installed.

The expected output is:

```text
x64\Debug\HelloWorld.sys
```

## Harness Test

Point an agent at `skills/windows-drv-harness/SKILL.md`, then give it a task
like this:

```text
Build example\HelloWorld, put the resulting HelloWorld.sys into the VMware
guest, load it with sc.exe, analyze the expected BSOD with WinDbg MCP, fix the
driver bug, rebuild, restore the snapshot, and retest until the driver loads
and unloads without another BSOD.
```

Expected first run:

- `sc start HelloWorld` triggers a guest BSOD.
- WinDbg reports bugcheck `0x7E SYSTEM_THREAD_EXCEPTION_NOT_HANDLED`.
- The exception code is `STATUS_ACCESS_VIOLATION`.
- The fault is in `HelloWorld!DriverEntry`.

Expected final run after the agent fixes the source:

- `sc create` and `sc start` return success.
- WinDbg `lm m HelloWorld` shows the module after load.
- There is no bugcheck while loading.
- `sc stop` and `sc delete` return success.
- WinDbg `lm m HelloWorld` no longer shows the module after unload.
- The VM is reverted to the configured VirtualKD-ready baseline snapshot.
