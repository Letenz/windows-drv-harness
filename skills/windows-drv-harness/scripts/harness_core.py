#!/usr/bin/env python3
"""Core runtime for the Windows driver harness.

The public methods return compact JSON-friendly dictionaries. Secrets are
accepted only from the user-level config and are never included in results.
"""

from __future__ import annotations

import contextlib
import csv
import ctypes
import json
import locale
import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Iterator

try:
    import msvcrt
except ImportError:  # pragma: no cover - this harness is Windows-only
    msvcrt = None


CONFIG_ENV = "WINDOWS_DRV_HARNESS_CONFIG"
CONFIG_VERSION = 2
PIPE_PREFIX = "\\\\.\\pipe\\"
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,240}$")
ENV_VALUE_RE = re.compile(r"^\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}$")


class HarnessError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        next_action: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_action = next_action
        self.details = details or {}

    def result(self, target: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "status": "blocked",
            "error_code": self.code,
            "message": self.message,
            "next_action": self.next_action,
        }
        if target:
            result["target"] = target
        if self.details:
            result["details"] = redact(self.details)
        return result


@dataclass
class CommandOutput:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    def summary(self, limit: int = 2000) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "output": _clip((self.stdout + "\n" + self.stderr).strip(), limit),
        }


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    tail = min(512, limit // 4)
    return value[: limit - tail] + "\n[...truncated...]\n" + value[-tail:]


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if any(word in lowered for word in ("password", "secret", "token", "api_key")):
                if isinstance(item, bool) or item is None:
                    result[key] = item
                else:
                    result[key] = "***" if item else ""
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "windows-drv-harness"
    return Path.home() / "AppData" / "Local" / "windows-drv-harness"


def default_config_path() -> Path:
    override = os.environ.get(CONFIG_ENV)
    return Path(override).expanduser() if override else data_dir() / "config.json"


def normalize_pipe(value: str) -> tuple[str, str]:
    raw = (value or "").strip().strip('"')
    if raw.lower().startswith(PIPE_PREFIX.lower()):
        name = raw[len(PIPE_PREFIX) :]
    else:
        name = raw
    if not SAFE_NAME_RE.fullmatch(name):
        raise HarnessError(
            "invalid_pipe",
            "The target MCP pipe name is invalid.",
            "Use only ASCII letters, digits, dot, underscore, or dash.",
        )
    return name, PIPE_PREFIX + name


def derived_pipe(target: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", target).strip("-.")
    if not safe:
        raise HarnessError(
            "invalid_target",
            "The target name cannot produce a safe pipe name.",
            "Rename the target using ASCII letters, digits, dot, underscore, or dash.",
        )
    return ("windbgmcp-" + safe)[:240]


def resolve_env_value(value: str) -> str:
    match = ENV_VALUE_RE.fullmatch(value or "")
    if not match:
        return value or ""
    return os.environ.get(match.group(1), "")


def load_config(path: str | Path | None = None) -> tuple[dict[str, Any], Path]:
    config_path = Path(path) if path else default_config_path()
    if not config_path.exists():
        raise HarnessError(
            "config_missing",
            f"User configuration does not exist: {config_path}",
            "Run configure-target.ps1 once, then retry lab_doctor.",
            {"config_path": str(config_path)},
        )
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(
            "config_invalid",
            "The user configuration is not valid JSON.",
            "Fix or recreate the config with configure-target.ps1.",
            {"config_path": str(config_path), "reason": str(exc)},
        ) from exc

    if "targets" not in config and "vm" in config:
        config = migrate_legacy_config(config)
    if config.get("version") != CONFIG_VERSION:
        raise HarnessError(
            "config_version",
            f"Expected config version {CONFIG_VERSION}.",
            "Run migrate-config.ps1 or recreate the user config.",
            {"config_path": str(config_path)},
        )
    if not isinstance(config.get("host"), dict) or not isinstance(config.get("targets"), dict):
        raise HarnessError(
            "config_invalid",
            "Config must contain host and targets objects.",
            "Recreate the config with configure-target.ps1.",
        )
    return config, config_path.resolve()


def migrate_legacy_config(config: dict[str, Any], target: str = "default") -> dict[str, Any]:
    vm = config.get("vm", {})
    guest = config.get("guest", {})
    flags = config.get("flags", {})
    return {
        "version": CONFIG_VERSION,
        "default_target": target,
        "host": config.get("host", {}),
        "targets": {
            target: {
                "vmx_path": vm.get("vmx_path", ""),
                "baseline_snapshot": vm.get("baseline_snapshot", ""),
                "mcp_pipe": derived_pipe(target),
                "guest": guest,
                "flags": flags,
            }
        },
    }


class Harness:
    def __init__(self, config_path: str | Path | None = None, skill_dir: str | Path | None = None):
        self.skill_dir = (
            Path(skill_dir).resolve()
            if skill_dir
            else Path(__file__).resolve().parents[1]
        )
        self.config, self.config_path = load_config(config_path)
        self.runtime_dir = self.config_path.parent
        self.state_dir = self.runtime_dir / "state"
        self.log_dir = self.runtime_dir / "logs"
        self.lock_dir = self.runtime_dir / "locks"
        for directory in (self.state_dir, self.log_dir, self.lock_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def _target_name(self, requested: str | None) -> str:
        targets = self.config["targets"]
        name = requested or self.config.get("default_target")
        if not name and len(targets) == 1:
            name = next(iter(targets))
        if not name:
            raise HarnessError(
                "target_required",
                "No target was supplied and no default target is configured.",
                "Call lab_list_targets and pass one returned target name.",
            )
        if name not in targets:
            raise HarnessError(
                "target_unknown",
                f"Unknown target: {name}",
                "Call lab_list_targets and use an exact target name.",
                {"available_targets": sorted(targets)},
            )
        return name

    def _context(self, requested: str | None) -> dict[str, Any]:
        name = self._target_name(requested)
        profile = self.config["targets"][name]
        if not isinstance(profile, dict):
            raise HarnessError(
                "target_invalid",
                f"Target {name} is not an object.",
                "Repair the target entry in the user config.",
            )
        guest = profile.get("guest", {})
        host = self.config.get("host", {})
        pipe_name, pipe_endpoint = normalize_pipe(profile.get("mcp_pipe") or derived_pipe(name))
        kd_pipe_name = ""
        kd_pipe_endpoint = ""
        if profile.get("kd_pipe"):
            kd_pipe_name, kd_pipe_endpoint = normalize_pipe(str(profile["kd_pipe"]))
        return {
            "name": name,
            "profile": profile,
            "guest": guest,
            "host": host,
            "vmx_path": str(profile.get("vmx_path", "")),
            "snapshot": str(profile.get("baseline_snapshot", "")),
            "pipe_name": pipe_name,
            "pipe_endpoint": pipe_endpoint,
            "kd_pipe_name": kd_pipe_name,
            "kd_pipe_endpoint": kd_pipe_endpoint,
            "windbg_mcp": str(self._bundled_windbg_mcp()),
            "mcpext": str(self.skill_dir / "windbg-mcp" / "mcpext.dll"),
            "vmrun": self._find_vmrun(host),
            "vmmon": self._find_vmmon(host),
            "windbg": self._find_windbg(host),
            "msbuild": self._find_msbuild(host),
        }

    def _bundled_windbg_mcp(self) -> Path:
        directory = self.skill_dir / "windbg-mcp"
        for name in ("windbg-mcp-v2.exe", "windbg-mcp.exe"):
            candidate = directory / name
            if candidate.is_file():
                return candidate
        return directory / "windbg-mcp.exe"

    def _first_existing(self, values: list[str | None]) -> str:
        for value in values:
            if value and Path(value).is_file():
                return str(Path(value).resolve())
        return ""

    def _registry_value(self, key_path: str, name: str, wow32: bool = False) -> str:
        try:
            import winreg

            access = winreg.KEY_READ
            if wow32:
                access |= winreg.KEY_WOW64_32KEY
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, access) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value)
        except (ImportError, OSError):
            return ""

    def _find_vmrun(self, host: dict[str, Any]) -> str:
        install = self._registry_value(
            r"SOFTWARE\VMware, Inc.\VMware Workstation", "InstallPath", wow32=True
        )
        return self._first_existing(
            [
                str(host.get("vmrun_path", "")),
                os.environ.get("VMRUN_PATH"),
                str(Path(install) / "vmrun.exe") if install else None,
                r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
                r"C:\Program Files\VMware\VMware Workstation\vmrun.exe",
            ]
        )

    def _find_vmmon(self, host: dict[str, Any]) -> str:
        return self._first_existing(
            [
                str(host.get("vmmon64_path", "")),
                os.environ.get("WINDOWS_DRV_HARNESS_VMMON64"),
                os.environ.get("VMMON64_PATH"),
                r"C:\Program Files\VirtualKD-Redux\vmmon64.exe",
                r"C:\Program Files (x86)\VirtualKD-Redux\vmmon64.exe",
            ]
        )

    def _find_windbg(self, host: dict[str, Any]) -> str:
        tools_path = self._registry_value(
            r"SOFTWARE\VirtualKD-Redux\Monitor", "ToolsPath"
        )
        return self._first_existing(
            [
                str(host.get("windbg_path", "")),
                os.environ.get("WINDBG_PATH"),
                str(Path(tools_path) / "windbg.exe") if tools_path else None,
                r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\windbg.exe",
                r"C:\Program Files\Windows Kits\10\Debuggers\x64\windbg.exe",
            ]
        )

    def _find_msbuild(self, host: dict[str, Any]) -> str:
        explicit = self._first_existing(
            [str(host.get("msbuild_path", "")), os.environ.get("MSBUILD_PATH")]
        )
        if explicit:
            return explicit
        task_dir = Path(r"C:\Program Files (x86)\Windows Kits\10\build\bin")
        task_majors = {
            match.group(1)
            for item in task_dir.glob("Microsoft.DriverKit.Build.Tasks.*.dll")
            if (match := re.search(r"Tasks\.(\d+)\.0\.dll$", item.name))
        }
        candidates = [
            ("17", r"C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe"),
            ("17", r"C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe"),
            ("17", r"D:\software\vs2022\MSBuild\Current\Bin\MSBuild.exe"),
            ("16", r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional\MSBuild\Current\Bin\MSBuild.exe"),
            ("16", r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\MSBuild\Current\Bin\MSBuild.exe"),
            ("15", r"C:\Program Files (x86)\Microsoft Visual Studio\2017\Professional\MSBuild\15.0\Bin\MSBuild.exe"),
        ]
        compatible = [path for major, path in candidates if major in task_majors and Path(path).is_file()]
        return str(Path(compatible[0]).resolve()) if compatible else ""

    def list_targets(self) -> dict[str, Any]:
        items = []
        default = self.config.get("default_target")
        for name in sorted(self.config["targets"]):
            profile = self.config["targets"][name]
            _, endpoint = normalize_pipe(profile.get("mcp_pipe") or derived_pipe(name))
            state = self._read_state(name)
            items.append(
                {
                    "name": name,
                    "default": name == default,
                    "mcp_pipe": endpoint,
                    "kd_pipe_configured": bool(profile.get("kd_pipe")),
                    "vmx_configured": bool(profile.get("vmx_path")),
                    "snapshot_configured": bool(profile.get("baseline_snapshot")),
                    "guest_credentials_configured": bool(
                        profile.get("guest", {}).get("admin_user")
                        and profile.get("guest", {}).get("admin_password")
                    ),
                    "session_status": state.get("status", "not_started"),
                }
            )
        return {
            "ok": True,
            "status": "targets_listed",
            "default_target": default,
            "targets": items,
            "next_action": "Call lab_doctor with the selected target.",
        }

    def doctor(self, requested: str | None = None) -> dict[str, Any]:
        ctx = self._context(requested)
        guest = ctx["guest"]
        checks: dict[str, Any] = {
            "config": True,
            "vmx": bool(ctx["vmx_path"] and Path(ctx["vmx_path"]).is_file()),
            "snapshot_name": bool(ctx["snapshot"]),
            "kd_pipe": bool(ctx["kd_pipe_endpoint"]),
            "guest_user": bool(guest.get("admin_user")),
            "guest_password": bool(resolve_env_value(str(guest.get("admin_password", "")))),
            "guest_deploy_dir": bool(guest.get("deploy_dir")),
            "vmrun": bool(ctx["vmrun"]),
            "vmmon_path": bool(ctx["vmmon"]),
            "windbg": bool(ctx["windbg"]),
            "windbg_mcp": Path(ctx["windbg_mcp"]).is_file(),
            "mcpext": Path(ctx["mcpext"]).is_file(),
            "msbuild": bool(ctx["msbuild"]),
            "is_admin": is_admin(),
        }
        vmmon_pids = process_ids("vmmon64.exe")
        checks["one_vmmon_running"] = len(vmmon_pids) == 1
        monitor = virtualkd_monitor()
        checks["virtualkd_manual_launch"] = (
            monitor.get("AutoInvokeDebugger") == 0
            and monitor.get("DebuggerType") == 2
        )

        snapshots: list[str] = []
        snapshot_verified = False
        if checks["vmrun"] and checks["vmx"]:
            output = self._vmrun(ctx, ["listSnapshots", ctx["vmx_path"]], "list snapshots", check=False)
            if output.exit_code == 0:
                snapshots = parse_snapshots(output.stdout)
                snapshot_verified = ctx["snapshot"] in snapshots
        checks["snapshot_exists"] = snapshot_verified

        required = [
            "vmx",
            "snapshot_name",
            "kd_pipe",
            "guest_user",
            "guest_password",
            "guest_deploy_dir",
            "vmrun",
            "vmmon_path",
            "windbg",
            "windbg_mcp",
            "mcpext",
            "one_vmmon_running",
            "virtualkd_manual_launch",
            "snapshot_exists",
        ]
        ready = all(checks[name] for name in required)
        failed = [name for name in required if not checks[name]]
        next_action = (
            "Call lab_start for this target."
            if ready
            else "Run setup-host.ps1 for host checks, then fix the listed target fields and retry lab_doctor."
        )
        return {
            "ok": ready,
            "status": "ready" if ready else "not_ready",
            "target": ctx["name"],
            "config_path": str(self.config_path),
            "mcp_pipe": ctx["pipe_endpoint"],
            "kd_pipe": ctx["kd_pipe_endpoint"],
            "checks": checks,
            "failed_checks": failed,
            "snapshot_names": snapshots,
            "vmmon_pids": vmmon_pids,
            "next_action": next_action,
        }

    def start(self, requested: str | None = None, timeout_seconds: int = 120) -> dict[str, Any]:
        ctx = self._context(requested)
        self._require_start_fields(ctx)

        state = self._read_state(ctx["name"])
        if (
            state.get("status") == "running"
            and pipe_exists(ctx["pipe_name"])
            and pid_running(int(state.get("windbg_pid", 0)))
        ):
            session = self._windbg_call(ctx, "wm_session", {}, 15)
            return {
                "ok": True,
                "status": "already_running",
                "target": ctx["name"],
                "mcp_pipe": ctx["pipe_endpoint"],
                "session": session,
                "next_action": "Call driver_test or debug_run for this target.",
            }

        with self._startup_lock(timeout_seconds + 60):
            vmmon_pids = process_ids("vmmon64.exe")
            if len(vmmon_pids) == 0:
                self._launch_vmmon(ctx)
                time.sleep(1)
                vmmon_pids = process_ids("vmmon64.exe")
            if len(vmmon_pids) != 1:
                raise HarnessError(
                    "vmmon_state",
                    f"Expected one vmmon64.exe process, found {len(vmmon_pids)}.",
                    "Run setup-host.ps1 and retry lab_start.",
                    {"vmmon_pids": vmmon_pids},
                )

            if self._vm_is_running(ctx):
                self._vmrun(ctx, ["stop", ctx["vmx_path"], "hard"], "stop target VM")
                if ctx["kd_pipe_name"]:
                    wait_for_pipe_absent(ctx["kd_pipe_name"], 15)
            existing_pipes = set(main_kd_pipes())
            self._vmrun(
                ctx,
                ["revertToSnapshot", ctx["vmx_path"], ctx["snapshot"]],
                "restore baseline snapshot",
                timeout=120,
            )
            if not self._vm_is_running(ctx):
                self._vmrun(ctx, ["start", ctx["vmx_path"], "nogui"], "start target VM", timeout=90)

            if ctx["kd_pipe_name"]:
                if not wait_for_pipe(ctx["kd_pipe_name"], timeout_seconds):
                    raise HarnessError(
                        "kd_pipe_timeout",
                        f"Configured VirtualKD pipe did not appear: {ctx['kd_pipe_endpoint']}",
                        "Verify the target kd_pipe binding and that vmmon64 was running before restore.",
                    )
                kd_pipe = ctx["kd_pipe_endpoint"]
            else:
                kd_pipe = self._wait_for_new_kd_pipe(existing_pipes, timeout_seconds)
            if pipe_exists(ctx["pipe_name"]):
                raise HarnessError(
                    "mcp_pipe_busy",
                    f"MCP endpoint is already in use: {ctx['pipe_endpoint']}",
                    "Reset the named target or choose a unique mcp_pipe in its profile.",
                )

            log_path = self.log_dir / (
                f"{safe_file_name(ctx['name'])}-{time.strftime('%Y%m%d-%H%M%S')}.log"
            )
            command = f".load {ctx['mcpext']}; !mcpext.start {ctx['pipe_name']}; g"
            win_args = [
                ctx["windbg"],
                "-logo",
                str(log_path),
                "-b",
                "-c",
                command,
                "-k",
                f"com:pipe,port={kd_pipe},resets=0,reconnect",
            ]
            win_proc = subprocess.Popen(win_args, close_fds=True)
            if not wait_for_pipe(ctx["pipe_name"], timeout_seconds):
                terminate_pid(win_proc.pid)
                raise HarnessError(
                    "windbg_bridge_timeout",
                    "WinDbg started but the target MCP endpoint did not appear.",
                    "Inspect the returned WinDbg log, then run lab_reset before retrying.",
                    {"log_path": str(log_path), "kd_pipe": kd_pipe},
                )

            session: dict[str, Any] = {}
            deadline = time.time() + timeout_seconds
            last_error: str | None = None
            while time.time() < deadline:
                try:
                    session = self._windbg_call(ctx, "wm_session", {}, 15)
                    if session.get("attached"):
                        break
                except HarnessError as exc:
                    last_error = exc.message
                time.sleep(1)
            if not session.get("attached"):
                terminate_pid(win_proc.pid)
                raise HarnessError(
                    "debugger_not_attached",
                    "The bridge is running but no attached debugger target was confirmed.",
                    "Inspect the WinDbg log and reset the target before retrying.",
                    {"log_path": str(log_path), "last_error": last_error},
                )

            state = {
                "version": 1,
                "target": ctx["name"],
                "status": "running",
                "vmx_path": ctx["vmx_path"],
                "snapshot": ctx["snapshot"],
                "kd_pipe": kd_pipe,
                "mcp_pipe": ctx["pipe_endpoint"],
                "windbg_pid": win_proc.pid,
                "log_path": str(log_path),
                "started_at": int(time.time()),
            }
            self._write_state(ctx["name"], state)
            return {
                "ok": True,
                "status": "running",
                "target": ctx["name"],
                "kd_pipe": kd_pipe,
                "mcp_pipe": ctx["pipe_endpoint"],
                "windbg_pid": win_proc.pid,
                "log_path": str(log_path),
                "session": session,
                "next_action": "Call driver_test or debug_run for this target.",
            }

    def debug_run(self, requested: str | None, command: str, timeout_ms: int = 30000) -> dict[str, Any]:
        ctx = self._context(requested)
        if not command.strip():
            raise HarnessError("command_required", "WinDbg command is empty.", "Pass a non-empty command.")
        result = self._windbg_call(
            ctx,
            "wm_run_cmd",
            {"cmd": command, "timeout_ms": timeout_ms},
            max(15, timeout_ms // 1000 + 10),
        )
        return {
            "ok": True,
            "status": "command_complete",
            "target": ctx["name"],
            "result": result,
            "next_action": "Continue debugging or call lab_reset when finished.",
        }

    def driver_build(
        self,
        solution_path: str,
        configuration: str = "Debug",
        platform: str = "x64",
    ) -> dict[str, Any]:
        solution = Path(solution_path).resolve()
        if not solution.is_file() or solution.suffix.lower() not in (".sln", ".vcxproj"):
            raise HarnessError(
                "project_missing",
                f"Driver solution/project does not exist: {solution}",
                "Pass an absolute .sln or .vcxproj path.",
            )
        host = self.config.get("host", {})
        msbuild = self._find_msbuild(host)
        if not msbuild:
            raise HarnessError(
                "msbuild_missing",
                "No MSBuild installation matches the installed WDK DriverKit tasks.",
                "Install matching Visual Studio WDK integration or set host.msbuild_path.",
            )
        before = {path.resolve(): path.stat().st_mtime for path in solution.parent.rglob("*.sys")}
        output = self._run(
            [
                msbuild,
                str(solution),
                "/m",
                f"/p:Configuration={configuration}",
                f"/p:Platform={platform}",
                "/v:minimal",
            ],
            "build driver",
            timeout=240,
        )
        binaries = sorted(
            solution.parent.rglob("*.sys"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        changed = [
            path
            for path in binaries
            if path.resolve() not in before or path.stat().st_mtime > before[path.resolve()]
        ]
        selected = changed[0] if changed else (binaries[0] if binaries else None)
        if not selected:
            raise HarnessError(
                "driver_output_missing",
                "MSBuild succeeded but no .sys output was found under the solution directory.",
                "Inspect the project output path and build log.",
                {"build": output.summary(4000)},
            )
        return {
            "ok": True,
            "status": "driver_built",
            "solution_path": str(solution),
            "sys_path": str(selected.resolve()),
            "configuration": configuration,
            "platform": platform,
            "msbuild_path": msbuild,
            "build": output.summary(4000),
            "next_action": "Call driver_test with this sys_path.",
        }

    def driver_test(
        self,
        requested: str | None,
        sys_path: str,
        service_name: str,
        expect: str = "success",
    ) -> dict[str, Any]:
        ctx = self._context(requested)
        if expect not in ("crash", "success"):
            raise HarnessError(
                "invalid_expectation",
                "expect must be crash or success.",
                "Use crash for the seeded failing run and success after the fix.",
            )
        driver = Path(sys_path).resolve()
        if not driver.is_file():
            raise HarnessError(
                "driver_missing",
                f"Driver binary does not exist: {driver}",
                "Build the driver and pass the absolute .sys path.",
            )
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", service_name):
            raise HarnessError(
                "invalid_service",
                "Service name contains unsupported characters.",
                "Use letters, digits, dot, underscore, or dash.",
            )

        self.start(ctx["name"])
        evidence: dict[str, Any] = {}
        cleanup: dict[str, Any] | None = None
        try:
            session = self._windbg_call(ctx, "wm_session", {}, 15)
            if str(session.get("exec_status", "")).upper() not in ("GO", "RUNNING"):
                self._windbg_call(ctx, "wm_run_cmd", {"cmd": "g", "timeout_ms": 5000}, 15)

            self._wait_for_tools(ctx, 120)
            deploy_dir = str(ctx["guest"].get("deploy_dir", ""))
            guest_path = str(PureWindowsPath(deploy_dir) / driver.name)
            copy_result = self._vmrun_guest(
                ctx,
                ["copyFileFromHostToGuest", ctx["vmx_path"], str(driver), guest_path],
                "copy driver to guest",
                timeout=90,
            )
            evidence["copy"] = copy_result.summary()

            self._run_sc(ctx, ["delete", service_name], "delete stale driver service", check=False)
            create = self._run_sc(
                ctx,
                [
                    "create",
                    service_name,
                    "type=",
                    "kernel",
                    "start=",
                    "demand",
                    "binPath=",
                    guest_path,
                ],
                "create driver service",
            )
            evidence["create"] = create.summary()
            if expect == "crash":
                start_box: dict[str, Any] = {}

                def start_driver() -> None:
                    try:
                        start_box["result"] = self._run_sc(
                            ctx,
                            ["start", service_name],
                            "start driver service",
                            check=False,
                            timeout=12,
                        )
                    except Exception as exc:
                        start_box["error"] = str(exc)

                start_thread = threading.Thread(target=start_driver, daemon=True)
                start_thread.start()
                event: dict[str, Any] = {}
                deadline = time.time() + 90
                last_session: dict[str, Any] = {}
                while time.time() < deadline:
                    last_session = self._windbg_call(ctx, "wm_session", {}, 15)
                    if last_session.get("bugcheck"):
                        event = {"kind": "bugcheck", "data": last_session["bugcheck"]}
                        break
                    time.sleep(1)
                if not event:
                    raise HarnessError(
                        "bugcheck_timeout",
                        "The expected crash did not reach a WinDbg bugcheck state.",
                        "Inspect the service start result and debugger session before retrying.",
                        {"session": last_session},
                    )
                start_thread.join(15)
                start_result = start_box.get("result")
                evidence["start"] = (
                    start_result.summary()
                    if isinstance(start_result, CommandOutput)
                    else {
                        "exit_code": None,
                        "timed_out": start_thread.is_alive(),
                        "output": start_box.get("error", "guest command ended with the crash"),
                    }
                )
                raw_path = self.log_dir / f"{safe_file_name(ctx['name'])}-crash-{int(time.time())}.txt"
                report = self._windbg_call(
                    ctx,
                    "wm_analyze_crash",
                    {"output_file": str(raw_path)},
                    150,
                )
                report.pop("raw", None)
                evidence["event"] = event
                evidence["crash"] = report
                evidence["crash_log"] = str(raw_path)
                return {
                    "ok": True,
                    "passed": bool(report.get("bugcheck")),
                    "status": "expected_crash_observed",
                    "target": ctx["name"],
                    "expect": expect,
                    "evidence": evidence,
                    "next_action": "Patch the root cause, rebuild, then call driver_test with expect=success.",
                }

            start_result = self._run_sc(
                ctx,
                ["start", service_name],
                "start driver service",
                check=False,
                timeout=60,
            )
            evidence["start"] = start_result.summary()
            if start_result.exit_code != 0:
                raise HarnessError(
                    "driver_start_failed",
                    "The driver did not start successfully and no crash was expected.",
                    "Inspect evidence.start and the debugger state before retrying.",
                    {"start": start_result.summary()},
                )
            self._windbg_call(ctx, "wm_break_in", {"timeout_ms": 30000}, 45)
            loaded = self._windbg_call(
                ctx, "wm_run_cmd", {"cmd": f"lm m {service_name}", "timeout_ms": 30000}, 45
            )
            evidence["module_loaded"] = loaded
            self._windbg_call(ctx, "wm_run_cmd", {"cmd": "g", "timeout_ms": 5000}, 15)
            stopped = self._run_sc(ctx, ["stop", service_name], "stop driver service")
            deleted = self._run_sc(ctx, ["delete", service_name], "delete driver service")
            evidence["stop"] = stopped.summary()
            evidence["delete"] = deleted.summary()
            self._windbg_call(ctx, "wm_break_in", {"timeout_ms": 30000}, 45)
            unloaded = self._windbg_call(
                ctx, "wm_run_cmd", {"cmd": f"lm m {service_name}", "timeout_ms": 30000}, 45
            )
            evidence["module_after_unload"] = unloaded
            self._windbg_call(ctx, "wm_run_cmd", {"cmd": "g", "timeout_ms": 5000}, 15)
            loaded_present = service_name.lower() in str(loaded.get("output", "")).lower()
            unloaded_absent = service_name.lower() not in str(unloaded.get("output", "")).lower()
            evidence["verification"] = {
                "module_loaded": loaded_present,
                "module_unloaded": unloaded_absent,
            }
            if not loaded_present or not unloaded_absent:
                raise HarnessError(
                    "module_verification_failed",
                    "Service commands completed, but WinDbg module evidence did not prove load and unload.",
                    "Inspect module_loaded/module_after_unload output and retry after a concrete fix.",
                    {"verification": evidence["verification"]},
                )
            return {
                "ok": True,
                "passed": True,
                "status": "driver_cycle_passed",
                "target": ctx["name"],
                "expect": expect,
                "evidence": evidence,
                "next_action": "The test passed; inspect cleanup to confirm the VM returned to baseline.",
            }
        finally:
            try:
                cleanup = self.reset(ctx["name"])
            except Exception as exc:  # cleanup failure must not hide primary evidence
                cleanup = {
                    "ok": False,
                    "status": "cleanup_failed",
                    "message": str(exc),
                    "next_action": "Call lab_reset for this target.",
                }
            evidence["cleanup"] = cleanup

    def reset(self, requested: str | None = None) -> dict[str, Any]:
        ctx = self._context(requested)
        state = self._read_state(ctx["name"])
        shutdown: dict[str, Any] | None = None
        if pipe_exists(ctx["pipe_name"]):
            try:
                shutdown = self._windbg_call(ctx, "wm_shutdown", {}, 20)
            except HarnessError as exc:
                shutdown = exc.result(ctx["name"])
        pid = int(state.get("windbg_pid", 0) or 0)
        if pid:
            terminate_pid(pid)
        if ctx["vmrun"] and ctx["vmx_path"] and Path(ctx["vmx_path"]).is_file():
            if self._vm_is_running(ctx):
                self._vmrun(ctx, ["stop", ctx["vmx_path"], "hard"], "stop target VM", check=False)
            if ctx["snapshot"]:
                self._vmrun(
                    ctx,
                    ["revertToSnapshot", ctx["vmx_path"], ctx["snapshot"]],
                    "restore baseline snapshot",
                    timeout=120,
                )
        final_state = {
            "version": 1,
            "target": ctx["name"],
            "status": "reverted",
            "snapshot": ctx["snapshot"],
            "updated_at": int(time.time()),
        }
        self._write_state(ctx["name"], final_state)
        return {
            "ok": True,
            "status": "reverted",
            "target": ctx["name"],
            "snapshot": ctx["snapshot"],
            "bridge_shutdown": shutdown,
            "next_action": "The target is back at baseline and can be started again.",
        }

    def _require_start_fields(self, ctx: dict[str, Any]) -> None:
        missing = []
        for name, value in (
            ("vmx_path", ctx["vmx_path"]),
            ("baseline_snapshot", ctx["snapshot"]),
            ("kd_pipe", ctx["kd_pipe_endpoint"]),
            ("guest.admin_user", ctx["guest"].get("admin_user")),
            ("guest.admin_password", resolve_env_value(str(ctx["guest"].get("admin_password", "")))),
            ("guest.deploy_dir", ctx["guest"].get("deploy_dir")),
            ("host.vmrun_path", ctx["vmrun"]),
            ("host.vmmon64_path", ctx["vmmon"]),
            ("host.windbg_path", ctx["windbg"]),
            ("bundled.windbg_mcp", Path(ctx["windbg_mcp"]).is_file()),
            ("bundled.mcpext", Path(ctx["mcpext"]).is_file()),
        ):
            if not value:
                missing.append(name)
        if ctx["vmx_path"] and not Path(ctx["vmx_path"]).is_file():
            missing.append("vmx_path_exists")
        if missing:
            raise HarnessError(
                "config_incomplete",
                "The target configuration is incomplete.",
                "Run lab_doctor, then update only the listed fields.",
                {"missing": missing},
            )
        monitor = virtualkd_monitor()
        if monitor.get("AutoInvokeDebugger") != 0 or monitor.get("DebuggerType") != 2:
            raise HarnessError(
                "host_setup_required",
                "VirtualKD host settings are not prepared for harness-managed WinDbg.",
                "Run setup-host.ps1 once from this skill, then retry.",
            )

    def _run(
        self,
        args: list[str],
        operation: str,
        timeout: int = 60,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> CommandOutput:
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding=locale.getpreferredencoding(False),
                errors="replace",
                timeout=timeout,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            output = CommandOutput(completed.returncode, completed.stdout, completed.stderr)
        except subprocess.TimeoutExpired as exc:
            output = CommandOutput(
                124,
                _as_text(exc.stdout),
                _as_text(exc.stderr),
                timed_out=True,
            )
        except OSError as exc:
            raise HarnessError(
                "process_start_failed",
                f"Could not start operation: {operation}",
                "Run lab_doctor and verify the configured tool path.",
                {"reason": str(exc)},
            ) from exc
        if check and output.exit_code != 0:
            raise HarnessError(
                "command_failed",
                f"Operation failed: {operation}",
                "Inspect the bounded command output, fix that gate, and retry once.",
                {"operation": operation, "result": output.summary()},
            )
        return output

    def _vmrun(
        self,
        ctx: dict[str, Any],
        args: list[str],
        operation: str,
        timeout: int = 60,
        check: bool = True,
    ) -> CommandOutput:
        return self._run([ctx["vmrun"], "-T", "ws", *args], operation, timeout, check)

    def _vmrun_guest(
        self,
        ctx: dict[str, Any],
        args: list[str],
        operation: str,
        timeout: int = 60,
        check: bool = True,
    ) -> CommandOutput:
        user = str(ctx["guest"].get("admin_user", ""))
        password = resolve_env_value(str(ctx["guest"].get("admin_password", "")))
        return self._run(
            [ctx["vmrun"], "-T", "ws", "-gu", user, "-gp", password, *args],
            operation,
            timeout,
            check,
        )

    def _run_sc(
        self,
        ctx: dict[str, Any],
        sc_args: list[str],
        operation: str,
        check: bool = True,
        timeout: int = 60,
    ) -> CommandOutput:
        return self._vmrun_guest(
            ctx,
            [
                "runProgramInGuest",
                ctx["vmx_path"],
                r"C:\Windows\System32\sc.exe",
                *sc_args,
            ],
            operation,
            timeout,
            check,
        )

    def _wait_for_tools(self, ctx: dict[str, Any], timeout_seconds: int) -> None:
        deadline = time.time() + timeout_seconds
        last = ""
        while time.time() < deadline:
            output = self._vmrun(
                ctx,
                ["checkToolsState", ctx["vmx_path"]],
                "check VMware Tools",
                timeout=15,
                check=False,
            )
            last = (output.stdout + output.stderr).strip()
            if output.exit_code == 0 and "running" in last.lower():
                return
            time.sleep(2)
        raise HarnessError(
            "vmware_tools_timeout",
            "VMware Tools did not become ready before the deadline.",
            "Verify the baseline snapshot and guest boot state, then reset and retry.",
            {"last_state": last},
        )

    def _vm_is_running(self, ctx: dict[str, Any]) -> bool:
        output = self._vmrun(ctx, ["list"], "list running VMs", check=False)
        target = os.path.normcase(os.path.abspath(ctx["vmx_path"]))
        for line in output.stdout.splitlines()[1:]:
            candidate = line.strip()
            if candidate and os.path.normcase(os.path.abspath(candidate)) == target:
                return True
        return False

    def _launch_vmmon(self, ctx: dict[str, Any]) -> None:
        if not ctx["vmmon"]:
            raise HarnessError(
                "vmmon_missing",
                "vmmon64.exe is not configured or discoverable.",
                "Run setup-host.ps1 so the elevated process can record its path.",
            )
        subprocess.Popen(
            [ctx["vmmon"]],
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _wait_for_new_kd_pipe(self, before: set[str], timeout_seconds: int) -> str:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            new = sorted(set(main_kd_pipes()) - before)
            if len(new) == 1:
                return new[0]
            if len(new) > 1:
                raise HarnessError(
                    "multiple_kd_pipes",
                    "More than one new VirtualKD pipe appeared during target startup.",
                    "Reset the target and start VMs one at a time so pipe ownership is unambiguous.",
                    {"pipes": new},
                )
            time.sleep(1)
        raise HarnessError(
            "kd_pipe_timeout",
            "No new VirtualKD main pipe appeared.",
            "Verify vmmon64 was running before restore and that the selected snapshot is debug-ready.",
        )

    def _windbg_call(
        self,
        ctx: dict[str, Any],
        tool: str,
        arguments: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        process = subprocess.Popen(
            [ctx["windbg_mcp"], "--pipe", ctx["pipe_name"]],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            _send_json(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "windows-drv-harness", "version": "2.0.0"},
                    },
                },
            )
            _read_rpc_response(process, 1, min(timeout_seconds, 15))
            _send_json(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            _send_json(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments},
                },
            )
            response = _read_rpc_response(process, 2, timeout_seconds)
            if "error" in response:
                raise HarnessError(
                    "windbg_mcp_error",
                    f"WinDbg MCP rejected {tool}.",
                    "Inspect the MCP error and debugger session state.",
                    {"error": response["error"]},
                )
            result = response.get("result", {})
            content = result.get("content", [])
            text = next(
                (item.get("text", "") for item in content if item.get("type") == "text"),
                "",
            )
            try:
                payload = json.loads(text) if text else {}
            except json.JSONDecodeError:
                payload = {"text": text}
            if result.get("isError") or payload.get("ok") is False:
                raise HarnessError(
                    "windbg_tool_failed",
                    f"WinDbg tool failed: {tool}",
                    "Use wm_session/debug_run evidence to correct the current debugger state.",
                    {"result": payload},
                )
            return payload
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

    @contextlib.contextmanager
    def _startup_lock(self, timeout_seconds: int) -> Iterator[None]:
        lock_path = self.lock_dir / "vm-start.lock"
        handle = lock_path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.time() + timeout_seconds
        acquired = False
        try:
            while time.time() < deadline:
                try:
                    handle.seek(0)
                    if msvcrt:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError:
                    time.sleep(0.2)
            if not acquired:
                raise HarnessError(
                    "startup_lock_timeout",
                    "Another target startup still owns the global VirtualKD pipe-discovery lock.",
                    "Wait for that startup to finish, then retry.",
                )
            yield
        finally:
            if acquired and msvcrt:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            handle.close()

    def _state_path(self, target: str) -> Path:
        return self.state_dir / f"{safe_file_name(target)}.json"

    def _read_state(self, target: str) -> dict[str, Any]:
        path = self._state_path(target)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_state(self, target: str, state: dict[str, Any]) -> None:
        path = self._state_path(target)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(temporary, path)


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def parse_snapshots(output: str) -> list[str]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if lines and lines[0].lower().startswith("total snapshots"):
        lines = lines[1:]
    return lines


def safe_file_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return safe or "target"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def process_ids(image_name: str) -> list[int]:
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    ids: list[int] = []
    for row in csv.reader(completed.stdout.splitlines()):
        if len(row) >= 2 and row[0].lower() == image_name.lower():
            try:
                ids.append(int(row[1]))
            except ValueError:
                pass
    return ids


def pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    process_query_limited_information = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def terminate_pid(pid: int) -> None:
    if pid <= 0 or not pid_running(pid):
        return
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def named_pipes() -> list[str]:
    try:
        return list(os.listdir(r"\\.\pipe"))
    except OSError:
        return []


def pipe_exists(pipe_name: str) -> bool:
    return pipe_name.lower() in {name.lower() for name in named_pipes()}


def wait_for_pipe(pipe_name: str, timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if pipe_exists(pipe_name):
            return True
        time.sleep(0.5)
    return False


def wait_for_pipe_absent(pipe_name: str, timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not pipe_exists(pipe_name):
            return True
        time.sleep(0.5)
    return False


def main_kd_pipes() -> list[str]:
    return [
        PIPE_PREFIX + name
        for name in named_pipes()
        if name.lower().startswith("kd_") and "_virtualkd_svc_" not in name.lower()
    ]


def virtualkd_monitor() -> dict[str, Any]:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\VirtualKD-Redux\Monitor",
            0,
            winreg.KEY_READ,
        ) as key:
            result: dict[str, Any] = {}
            for name in ("DebuggerType", "AutoInvokeDebugger", "InitialBreakIn", "WaitForOS"):
                try:
                    result[name] = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    result[name] = None
            return result
    except (ImportError, OSError):
        return {}


def _send_json(process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    if not process.stdin:
        raise HarnessError("mcp_stdio", "MCP stdin is unavailable.", "Restart the harness MCP server.")
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _readline_timeout(process: subprocess.Popen[str], timeout_seconds: int) -> str:
    if not process.stdout:
        return ""
    result: queue.Queue[str] = queue.Queue(maxsize=1)

    def reader() -> None:
        try:
            result.put(process.stdout.readline())
        except (OSError, ValueError):
            result.put("")

    threading.Thread(target=reader, daemon=True).start()
    try:
        return result.get(timeout=timeout_seconds)
    except queue.Empty as exc:
        raise HarnessError(
            "mcp_timeout",
            "Timed out waiting for the WinDbg MCP host.",
            "Inspect the target session and its endpoint, then retry once.",
        ) from exc


def _read_rpc_response(
    process: subprocess.Popen[str], request_id: int, timeout_seconds: int
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        line = _readline_timeout(process, max(1, int(deadline - time.time())))
        if not line:
            stderr = process.stderr.read() if process.stderr else ""
            raise HarnessError(
                "mcp_disconnected",
                "WinDbg MCP host exited before returning a response.",
                "Verify the endpoint and restart the target session.",
                {"stderr": _clip(stderr, 2000)},
            )
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("id") == request_id:
            return payload
    raise HarnessError(
        "mcp_timeout",
        "Timed out waiting for a matching WinDbg MCP response.",
        "Inspect the debugger log and retry once.",
    )
