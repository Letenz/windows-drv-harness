"""Environment diagnosis and VirtualKD monitor helpers."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from ..config import config_bool, config_value, load_config, repo_root


DEFAULT_VMRUN = r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe"


def _check(name: str, ok: bool, detail: str = "", hint: str = "") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail, "hint": hint}


def _tasklist_contains(image_name: str) -> bool:
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return False
    return image_name.lower() in (proc.stdout or "").lower()


def is_process_elevated() -> bool:
    """Return whether the current agent process is running elevated/admin."""
    if os.name == "nt":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    geteuid = getattr(os, "geteuid", None)
    if callable(geteuid):
        return geteuid() == 0
    return False


def is_pipe_available(pipe_name: str = r"\\.\pipe\windbgmcp", timeout_ms: int = 50) -> bool:
    """Return whether a Windows named pipe exists or has a connectable instance."""
    if os.name != "nt":
        return Path(pipe_name).exists()
    try:
        import pywintypes
        import win32pipe

        win32pipe.WaitNamedPipe(pipe_name, max(1, timeout_ms))
        return True
    except pywintypes.error as exc:
        code = getattr(exc, "winerror", exc.args[0] if exc.args else 0)
        return code == 231  # ERROR_PIPE_BUSY still means the server exists.
    except Exception:
        return Path(pipe_name).exists()


def _probe_registry_value(key_path: str, value_name: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        root_name, subkey = key_path.split("\\", 1)
        root = getattr(winreg, root_name)
        with winreg.OpenKey(root, subkey) as key:
            value, _kind = winreg.QueryValueEx(key, value_name)
            return str(value)
    except Exception:
        return ""


def probe_vmrun_path(config: dict[str, Any] | None = None, explicit: str = "") -> str:
    config = config or {}
    candidates = [
        explicit,
        config_value(config, "host.vmrun_path"),
        os.environ.get("VMRUN_PATH", ""),
        _probe_registry_value(r"HKEY_LOCAL_MACHINE\SOFTWARE\VMware, Inc.\VMware Workstation", "InstallPath"),
        _probe_registry_value(
            r"HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\VMware, Inc.\VMware Workstation",
            "InstallPath",
        ),
        DEFAULT_VMRUN,
        r"C:\Program Files\VMware\VMware Workstation\vmrun.exe",
    ]

    expanded: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        if candidate.lower().endswith("vmrun.exe"):
            expanded.append(candidate)
        else:
            expanded.append(str(Path(candidate) / "vmrun.exe"))

    for path in expanded:
        if Path(path).is_file():
            return path
    return ""


def probe_vmmon64_path(config: dict[str, Any] | None = None, explicit: str = "") -> str:
    config = config or {}
    candidates = [
        explicit,
        config_value(config, "host.vmmon64_path"),
        os.environ.get("DRIVER_HARNESS_VMMON64", ""),
        os.environ.get("VMMON64_PATH", ""),
        _probe_registry_value(
            r"HKEY_LOCAL_MACHINE\Software\VirtualKD-Redux\Monitor",
            "InstallPath",
        ),
        _probe_registry_value(
            r"HKEY_CURRENT_USER\Software\VirtualKD-Redux\Monitor",
            "InstallPath",
        ),
        r"C:\Program Files\VirtualKD-Redux\vmmon64.exe",
        r"C:\Program Files (x86)\VirtualKD-Redux\vmmon64.exe",
    ]
    return _first_existing_executable(candidates, "vmmon64.exe")


def _first_existing_executable(candidates: list[str], executable_name: str) -> str:
    """Check explicit/default paths only; never scan drives or recurse."""
    expanded: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        if candidate.lower().endswith(executable_name.lower()):
            expanded.append(candidate)
        else:
            expanded.append(str(Path(candidate) / executable_name))

    for path in expanded:
        if Path(path).is_file():
            return path
    return ""


def _programdata() -> Path:
    return Path(os.environ.get("ProgramData", r"C:\ProgramData"))


def probe_extension_path() -> str:
    candidates = [
        os.environ.get("DRIVER_HARNESS_EXT_DLL", ""),
        str(_programdata() / r"driver-harness-mcp\bin\windbgmcpExt.dll"),
        str(repo_root() / r"bin\windbgmcpExt.dll"),
    ]
    for path in candidates:
        if path and Path(path).is_file():
            return path
    return ""


def _validate_vkd_registry_for_mcp() -> tuple[bool, str, str]:
    debugger_type = _probe_registry_value(
        r"HKEY_LOCAL_MACHINE\Software\VirtualKD-Redux\Monitor", "DebuggerType"
    )
    template = _probe_registry_value(
        r"HKEY_LOCAL_MACHINE\Software\VirtualKD-Redux\Monitor", "CustomDebuggerTemplate"
    )
    if debugger_type != "2":
        return (
            False,
            f"DebuggerType={debugger_type or '<missing>'}",
            "Set VKD DebuggerType=2 (Custom). DebuggerType=3 can ignore CustomDebuggerTemplate.",
        )
    required = ["windbgmcpExt.dll", "!mcpstart", "-c"]
    missing = [item for item in required if item.lower() not in template.lower()]
    if missing:
        return (
            False,
            f"CustomDebuggerTemplate missing: {', '.join(missing)}",
            "Template must load windbgmcpExt.dll and run !mcpstart.",
        )
    return True, template, ""


def diagnose_environment(
    config_path: str = "",
    *,
    vmx_path: str = "",
    snapshot_name: str = "",
    guest_user: str = "",
    guest_password: str = "",
    vmrun_path: str = "",
    vmmon64_path: str = "",
    pipe_name: str = r"\\.\pipe\windbgmcp",
    check_guest: bool = False,
) -> dict:
    """Diagnose the host/guest prerequisites needed for automated driver tests.

    This is intentionally read-only. It does not revert, start, stop, or edit
    registry state. Set check_guest=True to run read-only vmrun checks against
    the configured VM if it is already running.
    """
    config = load_config(config_path or None, required=False)

    vmx = vmx_path or config_value(config, "vm.vmx_path")
    snapshot = snapshot_name or config_value(config, "vm.baseline_snapshot")
    user = guest_user or config_value(config, "guest.admin_user")
    password = guest_password or config_value(config, "guest.admin_password")
    vmrun = probe_vmrun_path(config, vmrun_path)
    vmmon = probe_vmmon64_path(config, vmmon64_path)
    ext_dll = probe_extension_path()
    baseline_flag = config_bool(config, "flags.baseline_snapshot_created")
    vkd_flag = config_bool(config, "flags.guest_vkd_installed")
    kdnet_flag = config_bool(config, "flags.guest_kdnet_configured")
    testsigning_flag = config_bool(config, "flags.guest_testsigning_enabled")
    elevated = is_process_elevated()

    checks: list[dict[str, Any]] = [
        _check("config file", bool(config), str(config_path or repo_root() / "driver-harness.config.json"),
               "Copy driver-harness.config.example.json to driver-harness.config.json and fill it in."),
        _check("vm.vmx_path", bool(vmx and Path(vmx).is_file()), vmx, "Set vm.vmx_path to the guest .vmx."),
        _check("vm.baseline_snapshot", bool(snapshot), snapshot, "Set vm.baseline_snapshot."),
        _check(
            "baseline snapshot marked created",
            (not config) or baseline_flag,
            str(baseline_flag),
            "Create the baseline only after VirtualKD/KDNET, VMware Tools, admin password, and debug boot are ready; then set flags.baseline_snapshot_created=true.",
        ),
        _check(
            "guest debug transport configured",
            (not config) or vkd_flag or kdnet_flag,
            f"guest_vkd_installed={vkd_flag}, guest_kdnet_configured={kdnet_flag}",
            "Install/configure VirtualKD-Redux guest support or KDNET before taking the baseline snapshot.",
        ),
        _check(
            "guest testsigning flag",
            (not config) or testsigning_flag,
            str(testsigning_flag),
            "Enable testsigning before the baseline snapshot when testing self-signed drivers.",
        ),
        _check("guest.admin_user", bool(user), user, "Set guest.admin_user."),
        _check("guest.admin_password", bool(password), "***" if password else "",
               "Set guest.admin_password or its referenced environment variable."),
        _check(
            "vmrun.exe",
            bool(vmrun),
            vmrun,
            "Set VMRUN_PATH or host.vmrun_path; do not scan the whole disk.",
        ),
        _check(
            "vmmon64.exe path",
            bool(vmmon),
            vmmon,
            "Ask the user for vmmon64.exe and set host.vmmon64_path; "
            "do not scan the whole disk.",
        ),
        _check("vmmon64.exe running", _tasklist_contains("vmmon64.exe"), "",
               "Launch vmmon64.exe before starting a debug-enabled guest."),
        _check(
            "agent elevated/admin",
            elevated,
            str(elevated).lower(),
            "Run the current agent/session as Administrator for HKLM registry writes "
            "and reliable vmmon restart.",
        ),
        _check("windbgmcpExt.dll", bool(ext_dll), ext_dll,
               "Run installer\\install.ps1 or set DRIVER_HARNESS_EXT_DLL."),
        _check("windbgmcp pipe", is_pipe_available(pipe_name), pipe_name,
               "The pipe appears only after VM + WinDbg + !mcpstart are ready."),
    ]

    debugger_type = _probe_registry_value(
        r"HKEY_LOCAL_MACHINE\Software\VirtualKD-Redux\Monitor", "DebuggerType"
    )
    template = _probe_registry_value(
        r"HKEY_LOCAL_MACHINE\Software\VirtualKD-Redux\Monitor", "CustomDebuggerTemplate"
    )
    checks.append(
        _check(
            "VKD DebuggerType=2",
            debugger_type == "2",
            debugger_type,
            "Run installer\\steps\\write-registry.ps1 as Administrator.",
        )
    )
    checks.append(
        _check(
            "VKD CustomDebuggerTemplate",
            bool(template and "windbgmcpExt.dll" in template and "!mcpstart" in template and "-c" in template),
            template[:180],
            "Template should launch WinDbg with -c, load windbgmcpExt.dll, and run !mcpstart.",
        )
    )

    if check_guest and vmrun and vmx:
        checks.extend(_diagnose_guest(vmrun, vmx, snapshot, user, password))

    blocking = [
        c
        for c in checks
        if not c["ok"]
        and c["name"]
        in {
            "vm.vmx_path",
            "vm.baseline_snapshot",
            "baseline snapshot marked created",
            "guest debug transport configured",
            "guest.admin_user",
            "guest.admin_password",
            "vmrun.exe",
            "vmmon64.exe path",
            "windbgmcpExt.dll",
            "VKD DebuggerType=2",
            "VKD CustomDebuggerTemplate",
        }
    ]
    return {
        "ok": not blocking,
        "ready_for_test": not blocking and is_pipe_available(pipe_name),
        "checks": checks,
        "resolved": {
            "vmx_path": vmx,
            "snapshot_name": snapshot,
            "guest_user": user,
            "vmrun_path": vmrun,
            "vmmon64_path": vmmon,
            "extension_path": ext_dll,
            "pipe_name": pipe_name,
        },
    }


def _diagnose_guest(
    vmrun: str,
    vmx: str,
    snapshot: str,
    user: str,
    password: str,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    try:
        snapshots = subprocess.run(
            [vmrun, "-T", "ws", "listSnapshots", vmx],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        checks.append(
            _check(
                "snapshot exists",
                snapshots.returncode == 0 and snapshot in (snapshots.stdout or ""),
                (snapshots.stdout or snapshots.stderr or "").strip()[:300],
                "Create or rename the baseline snapshot.",
            )
        )
    except Exception as exc:
        checks.append(_check("snapshot exists", False, str(exc), "Check vmrun and vmx path."))

    try:
        tools = subprocess.run(
            [vmrun, "-T", "ws", "checkToolsState", vmx],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        checks.append(
            _check(
                "VMware Tools state",
                tools.returncode == 0 and "running" in (tools.stdout or "").lower(),
                (tools.stdout or tools.stderr or "").strip(),
                "Start the VM and wait for VMware Tools.",
            )
        )
    except Exception as exc:
        checks.append(_check("VMware Tools state", False, str(exc), "Start the VM."))

    if user and password:
        try:
            auth = subprocess.run(
                [
                    vmrun,
                    "-T",
                    "ws",
                    "-gu",
                    user,
                    "-gp",
                    password,
                    "runProgramInGuest",
                    vmx,
                    r"C:\Windows\System32\cmd.exe",
                    "/c",
                    "exit",
                    "0",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            checks.append(
                _check(
                    "vmrun guest auth",
                    auth.returncode == 0,
                    (auth.stdout or auth.stderr or "").strip()[:300],
                    "Check guest user/password and admin rights.",
                )
            )
        except Exception as exc:
            checks.append(_check("vmrun guest auth", False, str(exc), "Check guest auth."))

    return checks


def start_vkd_monitor(
    config_path: str = "",
    *,
    vmmon64_path: str = "",
    wait_seconds: int = 5,
) -> dict:
    """Start VirtualKD-Redux vmmon64.exe if it is not already running."""
    if os.name != "nt":
        return {"ok": False, "message": "VirtualKD monitor is Windows-only."}

    elevated = is_process_elevated()
    registry_ok, registry_detail, registry_hint = _validate_vkd_registry_for_mcp()
    if not registry_ok:
        return {
            "ok": False,
            "message": "VirtualKD registry is not configured for WinDbg MCP autostart.",
            "detail": registry_detail,
            "hint": registry_hint,
            "agent_elevated": elevated,
        }

    if _tasklist_contains("vmmon64.exe"):
        return {
            "ok": True,
            "message": (
                "vmmon64.exe is already running. If the VKD registry was just changed, "
                "restart vmmon64.exe before restoring/starting the VM."
            ),
            "already_running": True,
            "agent_elevated": elevated,
        }

    config = load_config(config_path or None, required=False)
    vmmon = probe_vmmon64_path(config, vmmon64_path)
    if not vmmon:
        return {
            "ok": False,
            "message": "vmmon64.exe not found.",
            "hint": (
                "Ask the user for vmmon64.exe, then set host.vmmon64_path in "
                "driver-harness.config.json. Do not scan the whole disk."
            ),
            "agent_elevated": elevated,
        }

    try:
        creationflags = 0
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            [vmmon],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except Exception as exc:
        return {
            "ok": False,
            "message": f"failed to launch vmmon64.exe: {exc}",
            "path": vmmon,
            "hint": (
                "Run the current agent/session as Administrator, or start "
                "vmmon64.exe manually before restoring the VM."
            ),
            "agent_elevated": elevated,
        }

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _tasklist_contains("vmmon64.exe"):
            return {
                "ok": True,
                "message": "vmmon64.exe started.",
                "path": vmmon,
                "pid": proc.pid,
                "agent_elevated": elevated,
            }
        time.sleep(0.25)

    return {
        "ok": False,
        "message": "vmmon64.exe was launched but was not observed in tasklist.",
        "path": vmmon,
        "pid": proc.pid,
        "hint": (
            "If the process required UAC, rerun the current agent/session as "
            "Administrator or start vmmon64.exe manually."
        ),
        "agent_elevated": elevated,
    }
