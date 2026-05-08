# Configure the Guest VM

This is a one-time setup per VM. After it, you snapshot the VM and revert
to that snapshot for every test cycle.

## Recommended guest

- **Windows 10 19041+** or **Windows 11**
- 4 GB RAM, 2 vCPUs, 60 GB disk (minimum)
- Single user with Administrator privileges and a **non-empty password** (vmrun guest auth requires this)

## Step 1 — Enable kernel debugging

In an **elevated** PowerShell inside the guest:

```powershell
# Enable kernel debugging
bcdedit /debug on

# Allow loading test-signed drivers
bcdedit /set testsigning on

# (Optional) Disable automatic reboot on BSOD — gives you time to inspect
wmic recoveros set AutoReboot = False
wmic recoveros set DebugInfoType = 2  # Kernel memory dump
```

Restart the guest after this.

## Step 2 — Choose your KD transport

Pick one. **VirtualKD-Redux is recommended** (faster and snapshot-friendly), but KDNET works too.

### Option A — VirtualKD-Redux (recommended)

1. Inside the guest, run the **VirtualKD-Redux target installer** (`vminstall.exe`)
   from the same release ZIP you used on the host.
2. It adds a new boot entry "VKD-Redux" to the boot menu.
3. After reboot, pick the VKD-Redux entry. The kernel boots with VKD's modified KD client.

You can confirm it worked by running `bcdedit` and looking for the VKD-Redux entry, or by
checking that `kdclient64.dll` from VKD is loaded into `vmware-vmx.exe` on the host (after
the guest boots into the VKD entry).

### Option B — KDNET

```powershell
# Inside the guest, elevated
bcdedit /dbgsettings net hostip:<host_ip> port:50000 key:<your.key.string.here>
```

Where `<host_ip>` is your **host's NIC on the same VMnet as the guest** (typically `192.168.x.1`
for VMnet8 NAT). Check via `ipconfig` on the host.

> ⚠️ Don't pick the office / external NIC IP. It must be the host adapter that talks to the guest.

You'll also need to allow UDP `50000` inbound through Windows Firewall **on the host**:

```powershell
# Run on the HOST as Administrator
New-NetFirewallRule -DisplayName "KDNET 50000" -Direction Inbound -Protocol UDP -LocalPort 50000 -Action Allow
```

## Step 3 — Verify the guest user can be authenticated

vmrun's guest operations use VMCI (no network needed) but **require a real Windows username/password**.

```powershell
# On the host
$vmrun = "C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe"
& $vmrun -gu <guest_user> -gp <guest_password> runProgramInGuest <path_to.vmx> "C:\Windows\System32\cmd.exe" "/c echo hello"
```

If this works, vmrun guest commands work. Empty passwords are **rejected** by VMware Tools
even if the Windows account itself has no password — set a non-empty one.

## Step 4 — Pre-install useful debug tools

While not strictly required, these make life easier during testing:

- [`Sysinternals Suite`](https://learn.microsoft.com/sysinternals/) (Process Explorer, DbgView)
- [`PCHunter` / `System Informer`](https://systeminformer.sourceforge.io/) — process / kernel inspection
- A driver loader of your choice (e.g. [`OSR Loader`](https://www.osronline.com/article.cfm%5Eid=157.htm))
- `cmd` shortcut to a script that triggers BSOD on demand (useful for testing the harness):

  ```reg
  Windows Registry Editor Version 5.00
  [HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Services\kbdhid\Parameters]
  "CrashOnCtrlScroll"=dword:00000001
  ```

  After the reg + restart, pressing `Ctrl + ScrollLock + ScrollLock` triggers `0xE2 MANUALLY_INITIATED_CRASH`.

## Step 5 — Create the baseline snapshot

This is the **clean-room state** you'll revert to before every test cycle.

1. Boot the guest.
2. Wait for it to fully settle (services started, no Windows Update in progress).
3. (Optional) Open whatever default tools you want pre-loaded.
4. **Take a snapshot** named `test_mcp_ready` (use this exact name, our examples reference it).

```powershell
# On the host, optional CLI alternative to the VMware UI
$vmx = "C:\path\to\YourGuest.vmx"
& "$vmrun" snapshot $vmx "test_mcp_ready"
```

> Important: snapshot names are **case-sensitive** in `vmrun` and there's no way to address them by ID.
> Keep the name unique across all your snapshots.

## Step 6 — (Optional) Disable hibernation / fast startup
These can interfere with KD initialization on subsequent boots:

```powershell
powercfg /hibernate off
```

And via Control Panel → Power Options → "Choose what the power buttons do" → uncheck "Turn on fast startup".

## You're done

Your guest is now a reusable test target:

```
revertToSnapshot test_mcp_ready
   → guest boots into VKD entry
   → vmmon64 detects VM, launches WinDbg Preview with -c autoload
   → \\.\pipe\windbgmcp is ready
   → AI can drive the guest kernel
```

If anything's not working, run the host-side `installer\doctor.ps1` to see what's misconfigured.
