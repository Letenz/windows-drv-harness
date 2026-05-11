"""Small JSON-over-named-pipe client for windbgmcpExt.dll."""

from __future__ import annotations

import json
import os
import time
from typing import Any


class PipeError(RuntimeError):
    """Raised when the WinDbg MCP named pipe cannot be used."""

    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


class PipeClient:
    """Line-delimited JSON client for windbgmcpExt.dll's named pipe protocol."""

    def __init__(self, pipe_name: str):
        self.pipe_name = pipe_name
        self.handle = None

    def connect(self, timeout_seconds: int = 10) -> None:
        if os.name != "nt":
            raise PipeError("pipe_connect", "WinDbg named pipes are Windows-only.")
        try:
            import win32file
            import win32pipe
        except Exception as exc:
            raise PipeError("pipe_connect", f"pywin32 is required: {exc}") from exc

        deadline_ms = max(1, timeout_seconds * 1000)
        try:
            win32pipe.WaitNamedPipe(self.pipe_name, deadline_ms)
        except Exception as exc:
            raise PipeError("pipe_connect", f"{self.pipe_name} is not available: {exc}") from exc
        self.handle = win32file.CreateFile(
            self.pipe_name,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            None,
        )

    def close(self) -> None:
        if self.handle:
            try:
                import win32file

                win32file.CloseHandle(self.handle)
            except Exception:
                pass
        self.handle = None

    def send(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        *,
        read: bool = True,
        timeout_seconds: int = 30,
    ) -> dict[str, Any] | None:
        if not self.handle:
            raise PipeError("pipe_send", "pipe is not connected")
        try:
            import win32file
        except Exception as exc:
            raise PipeError("pipe_send", f"pywin32 is required: {exc}") from exc

        payload = {
            "type": "command",
            "command": command,
            "id": int(time.time() * 1000),
            "args": args or {},
        }
        data = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        win32file.WriteFile(self.handle, data)
        if not read:
            return None
        return self.read_response(timeout_seconds=timeout_seconds)

    def read_response(self, timeout_seconds: int = 30) -> dict[str, Any]:
        if not self.handle:
            raise PipeError("pipe_read", "pipe is not connected")
        try:
            import win32file
            import win32pipe
        except Exception as exc:
            raise PipeError("pipe_read", f"pywin32 is required: {exc}") from exc

        deadline = time.monotonic() + timeout_seconds
        chunks: list[bytes] = []
        while time.monotonic() < deadline:
            try:
                _buf, available, _left = win32pipe.PeekNamedPipe(self.handle, 0)
            except Exception as exc:
                raise PipeError("pipe_read", f"PeekNamedPipe failed: {exc}") from exc
            if available:
                _rc, data = win32file.ReadFile(self.handle, min(available, 8192))
                chunks.append(data)
                joined = b"".join(chunks)
                if b"\n" in joined:
                    line, _rest = joined.split(b"\n", 1)
                    return json.loads(line.decode("utf-8", errors="replace"))
            time.sleep(0.05)
        raise PipeError("pipe_read", f"timed out waiting for {self.pipe_name} response")
