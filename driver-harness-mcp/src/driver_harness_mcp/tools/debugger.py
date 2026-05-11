"""WinDbg session hygiene and target execution-state helpers."""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any

from .environment import is_pipe_available
from .windbg_pipe import PipeClient, PipeError


RUNNING_STATUS_NAMES = {
    "DEBUG_STATUS_GO",
    "DEBUG_STATUS_GO_HANDLED",
    "DEBUG_STATUS_GO_NOT_HANDLED",
    "DEBUG_STATUS_STEP_OVER",
    "DEBUG_STATUS_STEP_INTO",
    "DEBUG_STATUS_STEP_BRANCH",
    "DEBUG_STATUS_REVERSE_GO",
    "DEBUG_STATUS_REVERSE_STEP_BRANCH",
    "DEBUG_STATUS_REVERSE_STEP_OVER",
    "DEBUG_STATUS_REVERSE_STEP_INTO",
}

BROKEN_STATUS_NAMES = {
    "DEBUG_STATUS_BREAK",
    "DEBUG_STATUS_WAIT_INPUT",
    "DEBUG_STATUS_TIMEOUT",
}


def _is_harness_windbg(process: dict[str, Any]) -> bool:
    text = " ".join(
        str(process.get(key, "") or "")
        for key in ("Name", "ExecutablePath", "CommandLine")
    ).lower()
    markers = (
        "windbgmcpext.dll",
        "!mcpstart",
        r"\\.\pipe\windbgmcp",
        "com:pipe",
    )
    return any(marker in text for marker in markers)


def _windbg_processes() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []

    script = r"""
$items = Get-CimInstance Win32_Process |
  Where-Object { $_.Name -in @('windbg.exe', 'windbgx.exe', 'WinDbgX.exe') } |
  Select-Object ProcessId,Name,ExecutablePath,CommandLine,CreationDate
if ($null -eq $items) {
  @() | ConvertTo-Json -Compress
} else {
  @($items) | ConvertTo-Json -Compress
}
"""
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return []
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        parsed = [parsed]
    result: list[dict[str, Any]] = []
    for item in parsed or []:
        if not isinstance(item, dict):
            continue
        item["is_harness_mcp_session"] = _is_harness_windbg(item)
        result.append(item)
    return result


def list_windbg_processes(*, only_harness_mcp: bool = False) -> dict:
    """List host WinDbg processes and mark those that look harness-owned."""
    processes = _windbg_processes()
    if only_harness_mcp:
        processes = [proc for proc in processes if proc.get("is_harness_mcp_session")]
    return {
        "ok": True,
        "count": len(processes),
        "processes": processes,
    }


def cleanup_windbg_instances(
    *,
    only_harness_mcp: bool = True,
    force: bool = True,
    dry_run: bool = False,
    wait_seconds: int = 5,
) -> dict:
    """Terminate stale WinDbg instances before VirtualKD auto-starts a new one.

    By default this only targets processes whose command line looks like it was
    launched by this harness (for example it contains windbgmcpExt.dll or
    !mcpstart). This avoids killing unrelated manual debugging sessions.
    """
    processes = _windbg_processes()
    targets = [
        proc
        for proc in processes
        if (proc.get("is_harness_mcp_session") or not only_harness_mcp)
    ]
    result: dict[str, Any] = {
        "ok": True,
        "dry_run": dry_run,
        "only_harness_mcp": only_harness_mcp,
        "targets": targets,
        "terminated": [],
        "errors": [],
    }
    if dry_run:
        return result

    for proc in targets:
        pid = proc.get("ProcessId")
        if not pid:
            continue
        args = ["taskkill", "/PID", str(pid)]
        if force:
            args.append("/F")
        taskkill = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=max(5, wait_seconds),
            check=False,
        )
        entry = {
            "pid": pid,
            "name": proc.get("Name", ""),
            "returncode": taskkill.returncode,
            "stdout": (taskkill.stdout or "").strip(),
            "stderr": (taskkill.stderr or "").strip(),
        }
        if taskkill.returncode == 0:
            result["terminated"].append(entry)
        else:
            result["errors"].append(entry)

    if result["errors"]:
        result["ok"] = False
    time.sleep(min(max(wait_seconds, 0), 5))
    result["remaining"] = [
        proc for proc in _windbg_processes()
        if (proc.get("is_harness_mcp_session") or not only_harness_mcp)
    ]
    return result


def query_debugger_status(
    pipe_name: str = r"\\.\pipe\windbgmcp",
    *,
    timeout_seconds: int = 10,
) -> dict:
    """Ask windbgmcpExt.dll for the target execution state without changing it."""
    if not is_pipe_available(pipe_name, timeout_ms=250):
        return {
            "ok": False,
            "message": f"{pipe_name} is not available.",
            "pipe_name": pipe_name,
            "windbg_processes": list_windbg_processes()["processes"],
        }

    client = PipeClient(pipe_name)
    try:
        client.connect(timeout_seconds=timeout_seconds)
        response = client.send(
            "debugger_status",
            {"timeout_ms": timeout_seconds * 1000},
            timeout_seconds=timeout_seconds,
        )
    except PipeError as exc:
        return {
            "ok": False,
            "message": str(exc),
            "stage": exc.stage,
            "pipe_name": pipe_name,
            "windbg_processes": list_windbg_processes()["processes"],
        }
    finally:
        client.close()

    if not response:
        return {"ok": False, "message": "empty debugger_status response", "pipe_name": pipe_name}
    if response.get("status") != "success":
        return {
            "ok": False,
            "message": (
                "debugger_status failed; install the current windbgmcpExt.dll "
                "if this handler is missing."
            ),
            "response": response,
            "pipe_name": pipe_name,
            "windbg_processes": list_windbg_processes()["processes"],
        }

    status_name = str(response.get("execution_status_name", ""))
    return {
        "ok": True,
        "pipe_name": pipe_name,
        "execution_status": response.get("execution_status"),
        "execution_status_name": status_name,
        "is_running": bool(response.get("is_running", status_name in RUNNING_STATUS_NAMES)),
        "is_broken": bool(response.get("is_broken", status_name in BROKEN_STATUS_NAMES)),
        "can_execute_commands": bool(
            response.get("can_execute_commands", status_name not in RUNNING_STATUS_NAMES)
        ),
        "response": response,
        "windbg_processes": list_windbg_processes()["processes"],
    }


def _wait_for_state(
    pipe_name: str,
    predicate,
    *,
    timeout_seconds: int,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last = query_debugger_status(pipe_name, timeout_seconds=max(1, min(timeout_seconds, 5)))
    while time.monotonic() < deadline:
        if last.get("ok") and predicate(last):
            return last
        time.sleep(0.25)
        last = query_debugger_status(pipe_name, timeout_seconds=max(1, min(timeout_seconds, 5)))
    return last


def ensure_debugger_ready(
    pipe_name: str = r"\\.\pipe\windbgmcp",
    *,
    desired_state: str = "broken",
    continue_if_broken: bool = True,
    break_if_running: bool = True,
    timeout_seconds: int = 20,
    go_timeout_ms: int = 600000,
) -> dict:
    """Normalize the current WinDbg target state for the next automation step.

    desired_state:
      - ``broken``: command/inspection mode. Break in if the guest is running.
      - ``running``: guest/vmrun mode. Send ``g`` if WinDbg is stopped at kd>.
      - ``any``: only report state.
    """
    desired = desired_state.lower()
    if desired not in {"broken", "running", "any"}:
        return {"ok": False, "message": "desired_state must be broken, running, or any"}

    status = query_debugger_status(pipe_name, timeout_seconds=timeout_seconds)
    actions: list[dict[str, Any]] = []
    if not status.get("ok"):
        return {"ok": False, "message": "could not query debugger state", "status": status}

    if desired == "any":
        return {"ok": True, "state": status, "actions": actions}

    if desired == "running" and status.get("is_broken"):
        if not continue_if_broken:
            return {
                "ok": False,
                "message": "target is broken and continue_if_broken=false",
                "state": status,
            }
        client = PipeClient(pipe_name)
        try:
            client.connect(timeout_seconds=timeout_seconds)
            client.send(
                "execute_command",
                {"command": "g", "timeout_ms": go_timeout_ms},
                read=False,
            )
            actions.append({"action": "execute_command", "command": "g", "read_response": False})
        finally:
            client.close()
        status = _wait_for_state(
            pipe_name,
            lambda value: bool(value.get("is_running")),
            timeout_seconds=timeout_seconds,
        )

    if desired == "broken" and status.get("is_running"):
        if not break_if_running:
            return {
                "ok": False,
                "message": "target is running and break_if_running=false",
                "state": status,
            }
        client = PipeClient(pipe_name)
        try:
            client.connect(timeout_seconds=timeout_seconds)
            response = client.send(
                "break_in",
                {"timeout_ms": timeout_seconds * 1000},
                timeout_seconds=timeout_seconds + 5,
            )
            actions.append({"action": "break_in", "response": response})
        finally:
            client.close()
        status = _wait_for_state(
            pipe_name,
            lambda value: bool(value.get("can_execute_commands")),
            timeout_seconds=timeout_seconds,
        )

    ok = bool(status.get("ok"))
    if desired == "running":
        ok = ok and bool(status.get("is_running"))
    elif desired == "broken":
        ok = ok and bool(status.get("can_execute_commands"))

    return {
        "ok": ok,
        "desired_state": desired,
        "state": status,
        "actions": actions,
        "message": "debugger state is ready" if ok else "debugger state is not ready",
    }
