"""Tool: wait_mcp_ready — block until the WinDbg-MCP named pipe is healthy."""

from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def wait_mcp_ready(
    pipe_name: str = r"\\.\pipe\windbgmcp",
    timeout_seconds: int = 60,
    poll_interval_seconds: float = 1.0,
) -> dict:
    """Wait until the WinDbg-MCP named pipe exists.

    Useful as a final synchronization step after starting/reverting a VM.
    Returns immediately if the pipe is already present.

    Args:
        pipe_name: Full path to the named pipe (default ``\\.\pipe\windbgmcp``).
        timeout_seconds: Give up after this many seconds.
        poll_interval_seconds: How often to re-check.

    Returns:
        Dict with ``ok`` (bool), ``message`` (str), ``elapsed_seconds`` (float).
    """
    start = time.monotonic()
    deadline = start + timeout_seconds

    while True:
        if Path(pipe_name).exists():
            return {
                "ok": True,
                "message": f"{pipe_name} is ready.",
                "elapsed_seconds": time.monotonic() - start,
            }
        if time.monotonic() >= deadline:
            return {
                "ok": False,
                "message": f"{pipe_name} did not appear within {timeout_seconds}s.",
                "elapsed_seconds": time.monotonic() - start,
            }
        time.sleep(poll_interval_seconds)
