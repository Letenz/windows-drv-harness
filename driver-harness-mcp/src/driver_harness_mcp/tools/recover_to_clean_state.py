"""Tool: recover_to_clean_state — bring a VM back to a known-clean baseline."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .debugger import cleanup_windbg_instances, ensure_debugger_ready
from .environment import is_pipe_available

logger = logging.getLogger(__name__)


DEFAULT_VMRUN = r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe"


@dataclass
class RecoverResult:
    ok: bool
    message: str
    elapsed_seconds: float


def _vmrun_path() -> str:
    return os.environ.get("VMRUN_PATH", DEFAULT_VMRUN)


def _run_vmrun(args: list[str], timeout: int = 60) -> tuple[int, str]:
    cmd = [_vmrun_path(), *args]
    logger.debug("vmrun %s", " ".join(args))
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        return -1, f"vmrun timeout: {exc}"
    except FileNotFoundError:
        return -1, f"vmrun not found at {_vmrun_path()} (set VMRUN_PATH env var)"


def recover_to_clean_state(
    vmx_path: str,
    snapshot_name: str,
    *,
    nogui: bool = True,
    wait_for_pipe: bool = True,
    pipe_name: str = r"\\.\pipe\windbgmcp",
    timeout_seconds: int = 90,
    close_existing_windbg: bool = True,
    ensure_running: bool = True,
) -> dict:
    """Revert a VM to a snapshot and bring it back to a usable state.

    Steps:
      1. Optionally close stale harness-owned WinDbg/MCP sessions.
      2. ``vmrun revertToSnapshot`` (works regardless of current VM state).
      3. ``vmrun start`` (no-op if already running after revert).
      4. Optionally wait for the WinDbg-MCP named pipe to appear, signalling
         that the full debug stack (VKD-Redux + WinDbg + extension) is ready.
      5. Optionally continue from an initial ``kd>`` break state with ``g``.

    Args:
        vmx_path: Absolute path to the .vmx file.
        snapshot_name: Snapshot to revert to (case-sensitive).
        nogui: Pass ``nogui`` to ``vmrun start`` (recommended for automation).
        wait_for_pipe: After start, poll for the windbgmcp named pipe.
        pipe_name: Pipe path to wait for; default matches our extension.
        timeout_seconds: Overall timeout for the whole operation.
        close_existing_windbg: Terminate stale harness-owned WinDbg instances
            before restoring the snapshot, so the MCP pipe cannot attach to an
            old session.
        ensure_running: After pipe readiness, send ``g`` if the target is
            stopped at ``kd>`` and the next step expects a live guest.

    Returns:
        Dict with keys ``ok`` (bool), ``message`` (str), ``elapsed_seconds`` (float).
    """
    start = time.monotonic()
    deadline = start + timeout_seconds

    if not Path(vmx_path).is_file():
        return RecoverResult(False, f"vmx not found: {vmx_path}", 0.0).__dict__

    artifacts = {}

    if close_existing_windbg:
        artifacts["cleanup_windbg_instances"] = cleanup_windbg_instances(
            only_harness_mcp=True,
            force=True,
        )

    # Step 1 — revert
    rc, out = _run_vmrun(["revertToSnapshot", vmx_path, snapshot_name], timeout=60)
    if rc != 0:
        result = RecoverResult(
            False, f"revertToSnapshot failed (rc={rc}): {out.strip()}", time.monotonic() - start
        ).__dict__
        result["artifacts"] = artifacts
        return result

    # Step 2 — start
    start_args = ["start", vmx_path]
    if nogui:
        start_args.append("nogui")
    rc, out = _run_vmrun(start_args, timeout=60)
    if rc != 0:
        result = RecoverResult(
            False, f"start failed (rc={rc}): {out.strip()}", time.monotonic() - start
        ).__dict__
        result["artifacts"] = artifacts
        return result

    # Step 3 — wait for pipe (optional)
    if wait_for_pipe:
        while time.monotonic() < deadline:
            if is_pipe_available(pipe_name, timeout_ms=250):
                if ensure_running:
                    artifacts["ensure_debugger_running"] = ensure_debugger_ready(
                        pipe_name,
                        desired_state="running",
                        continue_if_broken=True,
                    )
                    if not artifacts["ensure_debugger_running"].get("ok"):
                        result = RecoverResult(
                            False,
                            f"VM started but debugger was not running: "
                            f"{artifacts['ensure_debugger_running'].get('message')}",
                            time.monotonic() - start,
                        ).__dict__
                        result["artifacts"] = artifacts
                        return result
                result = RecoverResult(
                    True,
                    f"VM reverted, started, and {pipe_name} ready.",
                    time.monotonic() - start,
                ).__dict__
                result["artifacts"] = artifacts
                return result
            time.sleep(1.0)
        result = RecoverResult(
            False,
            f"VM reverted and started, but {pipe_name} did not appear within {timeout_seconds}s.",
            time.monotonic() - start,
        ).__dict__
        result["artifacts"] = artifacts
        return result

    result = RecoverResult(
        True,
        "VM reverted and started (pipe wait skipped).",
        time.monotonic() - start,
    ).__dict__
    result["artifacts"] = artifacts
    return result
