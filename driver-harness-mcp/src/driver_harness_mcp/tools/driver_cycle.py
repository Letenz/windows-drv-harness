"""High-level driver load/verify/unload test cycle."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from ..config import config_value, load_config
from .debugger import cleanup_windbg_instances, ensure_debugger_ready
from .environment import is_pipe_available, probe_vmrun_path, start_vkd_monitor
from .windbg_pipe import PipeClient, PipeError


class HarnessError(RuntimeError):
    def __init__(self, stage: str, message: str, *, detail: str = ""):
        super().__init__(message)
        self.stage = stage
        self.detail = detail


def run_driver_load_verify(
    sys_path: str,
    *,
    service_name: str = "HelloWord",
    load_marker: str = "[HelloWord] Hello World from kernel!",
    unload_marker: str = "[HelloWord] Driver unload, bye!",
    config_path: str = "",
    vmx_path: str = "",
    snapshot_name: str = "",
    guest_user: str = "",
    guest_password: str = "",
    guest_sys_path: str = "",
    vmrun_path: str = "",
    vmmon64_path: str = "",
    pipe_name: str = r"\\.\pipe\windbgmcp",
    ensure_vmmon: bool = True,
    close_existing_windbg: bool = True,
    pipe_timeout_seconds: int = 120,
    command_timeout_ms: int = 600000,
    always_revert: bool = True,
) -> dict:
    """Run a non-destructive driver load/verify/unload cycle.

    The tool owns the tricky WinDbg/guest scheduling interleave. The AI should
    call this instead of generating ad-hoc PowerShell for normal load tests.
    """
    started = time.monotonic()
    config = load_config(config_path or None, required=False)

    vmx = vmx_path or config_value(config, "vm.vmx_path")
    snapshot = snapshot_name or config_value(config, "vm.baseline_snapshot")
    user = guest_user or config_value(config, "guest.admin_user")
    password = guest_password or config_value(config, "guest.admin_password")
    vmrun = probe_vmrun_path(config, vmrun_path)
    desktop = config_value(config, "guest.desktop_path", rf"C:\Users\{user}\Desktop")
    guest_sys = guest_sys_path or rf"{desktop}\{Path(sys_path).name}"

    artifacts: dict[str, Any] = {}
    observations: list[str] = []
    timings: dict[str, float] = {}
    ctrl: PipeClient | None = None
    run: PipeClient | None = None

    def fail(stage: str, message: str, *, detail: str = "") -> dict[str, Any]:
        return {
            "verdict": "FAIL",
            "failed_stage": stage,
            "message": message,
            "detail": detail,
            "observations": observations,
            "artifacts": artifacts,
            "timings": timings,
            "elapsed_seconds": time.monotonic() - started,
        }

    validation = _validate_inputs(vmx, snapshot, user, password, vmrun, sys_path)
    if validation:
        return fail("validate_inputs", validation)

    try:
        if ensure_vmmon:
            mon = start_vkd_monitor(config_path=config_path, vmmon64_path=vmmon64_path)
            artifacts["start_vkd_monitor"] = mon
            if not mon.get("ok"):
                raise HarnessError("start_vkd_monitor", mon.get("message", "vmmon64 failed"))

        if close_existing_windbg:
            artifacts["cleanup_windbg_instances"] = cleanup_windbg_instances(
                only_harness_mcp=True,
                force=True,
            )

        _timed(
            timings,
            "revert",
            lambda: _run_vmrun(vmrun, ["revertToSnapshot", vmx, snapshot], 90),
        )
        _timed(timings, "start_vm", lambda: _run_vmrun(vmrun, ["start", vmx, "nogui"], 90))

        _wait_for_pipe(pipe_name, pipe_timeout_seconds)
        timings["wait_for_pipe"] = time.monotonic() - started - sum(timings.values())

        ready = ensure_debugger_ready(
            pipe_name,
            desired_state="broken",
            break_if_running=True,
            timeout_seconds=20,
        )
        artifacts["ensure_debugger_broken"] = ready
        if not ready.get("ok"):
            raise HarnessError(
                "ensure_debugger_broken",
                ready.get("message", "debugger is not command-ready"),
                detail=json.dumps(ready),
            )

        ctrl = PipeClient(pipe_name)
        run = PipeClient(pipe_name)
        ctrl.connect(timeout_seconds=10)
        run.connect(timeout_seconds=10)

        vt = _exec(ctrl, "vertarget", timeout_ms=30000)
        artifacts["vertarget"] = vt
        if vt.get("status") != "success":
            raise HarnessError("vertarget", "vertarget failed", detail=json.dumps(vt))

        mask = _exec(ctrl, "ed nt!Kd_DEFAULT_Mask 0xFFFFFFFF", timeout_ms=30000)
        artifacts["dbgprint_mask"] = mask
        if mask.get("status") != "success":
            observations.append("Could not set nt!Kd_DEFAULT_Mask; DbgPrint verification may fail.")

        def push_driver() -> dict[str, Any]:
            _wait_tools_running(vmrun, vmx, timeout_seconds=120)
            _run_vmrun(vmrun, ["-gu", user, "-gp", password, "copyFileFromHostToGuest", vmx, sys_path, guest_sys], 120)
            _run_vmrun(vmrun, ["-gu", user, "-gp", password, "fileExistsInGuest", vmx, guest_sys], 30)
            return {"guest_sys_path": guest_sys}

        artifacts["push_driver"] = _with_guest_running(
            run, ctrl, push_driver, command_timeout_ms=command_timeout_ms
        )

        host_query_file = str(Path(tempfile.gettempdir()) / f"{service_name}_sc_query.txt")
        guest_query_file = rf"{desktop}\{service_name}_sc_query.txt"

        def load_driver() -> dict[str, Any]:
            _run_vmrun(
                vmrun,
                [
                    "-gu", user, "-gp", password, "runProgramInGuest", vmx,
                    r"C:\Windows\System32\sc.exe",
                    "delete", service_name,
                ],
                30,
                allow_fail=True,
            )
            create = _run_vmrun(
                vmrun,
                [
                    "-gu", user, "-gp", password, "runProgramInGuest", vmx,
                    r"C:\Windows\System32\sc.exe",
                    "create", service_name, "type=", "kernel", "start=", "demand",
                    "binPath=", guest_sys,
                ],
                60,
            )
            start_result = _run_vmrun(
                vmrun,
                [
                    "-gu", user, "-gp", password, "runProgramInGuest", vmx,
                    r"C:\Windows\System32\sc.exe", "start", service_name,
                ],
                90,
                allow_fail=True,
            )
            _run_vmrun(
                vmrun,
                [
                    "-gu", user, "-gp", password, "runProgramInGuest", vmx,
                    r"C:\Windows\System32\cmd.exe", "/c",
                    f'sc query {service_name} > "{guest_query_file}"',
                ],
                30,
            )
            _run_vmrun(
                vmrun,
                [
                    "-gu", user, "-gp", password, "copyFileFromGuestToHost",
                    vmx, guest_query_file, host_query_file,
                ],
                30,
            )
            sc_query = Path(host_query_file).read_text(encoding="utf-8", errors="replace")
            return {"sc_create": create, "sc_start": start_result, "sc_query": sc_query}

        artifacts["load_driver"] = _with_guest_running(
            run, ctrl, load_driver, command_timeout_ms=command_timeout_ms
        )
        if "RUNNING" not in artifacts["load_driver"].get("sc_query", ""):
            raise HarnessError("sc_query", "driver service is not RUNNING",
                               detail=artifacts["load_driver"].get("sc_query", ""))

        lm = _exec(ctrl, f"lm m {service_name}", timeout_ms=30000)
        dp = _exec(ctrl, ".dbgprint", timeout_ms=60000)
        artifacts["lm_after_load"] = lm
        artifacts["dbgprint_after_load"] = _tail_response(dp)
        lm_text = _response_text(lm)
        dp_text = _response_text(dp)
        if service_name.lower() not in lm_text.lower():
            raise HarnessError("lm_after_load", f"{service_name} is not listed in lm output",
                               detail=lm_text)
        if load_marker and load_marker not in dp_text:
            raise HarnessError("dbgprint_load_marker", "load marker not found in .dbgprint",
                               detail=_tail(dp_text))

        def unload_driver() -> dict[str, Any]:
            stop = _run_vmrun(
                vmrun,
                [
                    "-gu", user, "-gp", password, "runProgramInGuest", vmx,
                    r"C:\Windows\System32\sc.exe", "stop", service_name,
                ],
                60,
                allow_fail=True,
            )
            delete = _run_vmrun(
                vmrun,
                [
                    "-gu", user, "-gp", password, "runProgramInGuest", vmx,
                    r"C:\Windows\System32\sc.exe", "delete", service_name,
                ],
                60,
                allow_fail=True,
            )
            return {"sc_stop": stop, "sc_delete": delete}

        artifacts["unload_driver"] = _with_guest_running(
            run, ctrl, unload_driver, command_timeout_ms=command_timeout_ms
        )

        dp2 = _exec(ctrl, ".dbgprint", timeout_ms=60000)
        lm2 = _exec(ctrl, f"lm m {service_name}", timeout_ms=30000)
        artifacts["dbgprint_after_unload"] = _tail_response(dp2)
        artifacts["lm_after_unload"] = lm2
        dp2_text = _response_text(dp2)
        lm2_text = _response_text(lm2)
        if unload_marker and unload_marker not in dp2_text:
            raise HarnessError("dbgprint_unload_marker", "unload marker not found in .dbgprint",
                               detail=_tail(dp2_text))
        if service_name.lower() in lm2_text.lower():
            raise HarnessError("lm_after_unload", f"{service_name} still appears in lm output",
                               detail=lm2_text)

        return {
            "verdict": "PASS",
            "failed_stage": "",
            "message": "driver loaded, printed markers, and unloaded cleanly",
            "service_name": service_name,
            "guest_sys_path": guest_sys,
            "observations": observations,
            "artifacts": artifacts,
            "timings": timings,
            "elapsed_seconds": time.monotonic() - started,
        }
    except HarnessError as exc:
        return fail(exc.stage, str(exc), detail=exc.detail)
    except PipeError as exc:
        return fail(exc.stage, str(exc))
    except Exception as exc:
        return fail("unexpected", str(exc))
    finally:
        if ctrl:
            ctrl.close()
        if run:
            run.close()
        if always_revert and vmrun and vmx and snapshot:
            try:
                t0 = time.monotonic()
                _run_vmrun(vmrun, ["revertToSnapshot", vmx, snapshot], 90, allow_fail=True)
                timings["final_revert"] = time.monotonic() - t0
            except Exception as exc:
                artifacts["final_revert_error"] = str(exc)


def _validate_inputs(vmx: str, snapshot: str, user: str, password: str, vmrun: str, sys_path: str) -> str:
    if not vmx or not Path(vmx).is_file():
        return f"vmx_path is missing or invalid: {vmx}"
    if not snapshot:
        return "snapshot_name is missing"
    if not user:
        return "guest_user is missing"
    if not password:
        return "guest_password is missing"
    if not vmrun or not Path(vmrun).is_file():
        return f"vmrun.exe is missing or invalid: {vmrun}"
    if not sys_path or not Path(sys_path).is_file():
        return f"sys_path is missing or invalid: {sys_path}"
    return ""


def _run_vmrun(
    vmrun: str,
    args: list[str],
    timeout_seconds: int,
    *,
    allow_fail: bool = False,
) -> dict[str, Any]:
    proc = subprocess.run(
        [vmrun, "-T", "ws", *args],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    result = {
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
        "command": ["vmrun", "-T", "ws", *args],
    }
    if proc.returncode != 0 and not allow_fail:
        raise HarnessError("vmrun", f"vmrun failed rc={proc.returncode}", detail=json.dumps(result))
    return result


def _timed(timings: dict[str, float], name: str, func: Callable[[], Any]) -> Any:
    start = time.monotonic()
    try:
        return func()
    finally:
        timings[name] = time.monotonic() - start


def _wait_for_pipe(pipe_name: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if is_pipe_available(pipe_name, timeout_ms=250):
            return
        time.sleep(0.5)
    raise HarnessError("wait_for_pipe", f"{pipe_name} did not appear within {timeout_seconds}s")


def _wait_tools_running(vmrun: str, vmx: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last = ""
    while time.monotonic() < deadline:
        proc = subprocess.run(
            [vmrun, "-T", "ws", "checkToolsState", vmx],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        last = (proc.stdout or proc.stderr or "").strip()
        if proc.returncode == 0 and "running" in last.lower():
            return
        time.sleep(1.0)
    raise HarnessError("wait_vmtools", f"VMware Tools did not reach running state: {last}")


def _exec(pipe: PipeClient, command: str, *, timeout_ms: int) -> dict[str, Any]:
    response = pipe.send(
        "execute_command",
        {"command": command, "timeout_ms": timeout_ms},
        timeout_seconds=max(5, timeout_ms // 1000 + 5),
    )
    assert response is not None
    return response


def _with_guest_running(
    run_pipe: PipeClient,
    ctrl_pipe: PipeClient,
    callback: Callable[[], dict[str, Any]],
    *,
    command_timeout_ms: int,
) -> dict[str, Any]:
    run_pipe.send(
        "execute_command",
        {"command": "g", "timeout_ms": command_timeout_ms},
        read=False,
    )
    time.sleep(0.5)
    callback_result: dict[str, Any] | None = None
    callback_error: Exception | None = None
    try:
        callback_result = callback()
    except Exception as exc:
        callback_error = exc
    finally:
        break_response = ctrl_pipe.send("break_in", {"timeout_ms": 10000}, timeout_seconds=15)
        try:
            run_response = run_pipe.read_response(timeout_seconds=20)
        except Exception as exc:
            run_response = {"status": "warning", "error": str(exc)}

    if callback_error:
        if isinstance(callback_error, HarnessError):
            raise callback_error
        raise HarnessError("guest_running_callback", str(callback_error))
    assert callback_result is not None
    callback_result["break_in"] = break_response
    callback_result["g_response"] = run_response
    return callback_result


def _response_text(response: dict[str, Any]) -> str:
    value = response.get("output")
    if value is None:
        value = response.get("result")
    if value is None:
        value = response.get("error")
    return str(value or "")


def _tail(text: str, lines: int = 40) -> str:
    return "\n".join(text.splitlines()[-lines:])


def _tail_response(response: dict[str, Any], lines: int = 40) -> dict[str, Any]:
    clone = dict(response)
    text = _response_text(response)
    if text:
        clone["tail"] = _tail(text, lines)
    return clone
