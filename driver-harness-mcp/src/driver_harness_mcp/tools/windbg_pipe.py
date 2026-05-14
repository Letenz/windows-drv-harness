"""Length-prefixed JSON client for the self-hosted mcpext.dll pipe protocol."""

from __future__ import annotations

import json
import os
import struct
import time
from typing import Any


MAX_FRAME_BYTES = 16 * 1024 * 1024


class PipeError(RuntimeError):
    """Raised when the WinDbg MCP named pipe cannot be used."""

    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


class PipeClient:
    """Single-connection client for mcpext.dll's multiplexed pipe protocol."""

    def __init__(self, pipe_name: str):
        self.pipe_name = pipe_name
        self.handle = None
        self._next_id = int(time.time() * 1000) & 0x7FFFFFFF
        self._last_request_id: int | None = None
        self._pending_responses: dict[int, dict[str, Any]] = {}

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
        op: str,
        args: dict[str, Any] | None = None,
        *,
        read: bool = True,
        timeout_seconds: int = 30,
    ) -> dict[str, Any] | None:
        """Send a protocol request.

        When ``read`` is false, the request remains in-flight and the returned
        ``request_id`` can later be passed to ``read_response``.
        """
        if not self.handle:
            raise PipeError("pipe_send", "pipe is not connected")

        req_id = self._allocate_request_id()
        self._last_request_id = req_id
        self._write_frame(
            {
                "frame": "req",
                "id": req_id,
                "op": op,
                "args": args or {},
            }
        )
        if not read:
            return {"request_id": req_id}
        return self.read_response(timeout_seconds=timeout_seconds, request_id=req_id)

    def read_response(
        self,
        timeout_seconds: int = 30,
        *,
        request_id: int | None = None,
    ) -> dict[str, Any]:
        if not self.handle:
            raise PipeError("pipe_read", "pipe is not connected")
        req_id = request_id if request_id is not None else self._last_request_id
        if req_id is None:
            raise PipeError("pipe_read", "request_id is required")
        if req_id in self._pending_responses:
            return self._pending_responses.pop(req_id)

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            frame = self._read_frame(deadline)
            kind = frame.get("frame")
            if kind == "resp":
                frame_id = int(frame.get("id", -1))
                response = self._normalize_response(frame)
                if frame_id == req_id:
                    return response
                self._pending_responses[frame_id] = response
            # Events and chunks are consumed here. The high-level harness tools
            # use request/response operations; event waiting is exposed by the
            # standalone windbg-mcp.exe MCP server.
        raise PipeError("pipe_read", f"timed out waiting for {self.pipe_name} response")

    def _allocate_request_id(self) -> int:
        self._next_id = (self._next_id + 1) & 0x7FFFFFFF
        if self._next_id == 0:
            self._next_id = 1
        return self._next_id

    def _write_frame(self, payload: dict[str, Any]) -> None:
        try:
            import win32file
        except Exception as exc:
            raise PipeError("pipe_send", f"pywin32 is required: {exc}") from exc

        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_FRAME_BYTES:
            raise PipeError("pipe_send", f"frame too large: {len(body)} bytes")
        win32file.WriteFile(self.handle, struct.pack("<I", len(body)) + body)

    def _read_frame(self, deadline: float) -> dict[str, Any]:
        header = self._read_exact(4, deadline)
        length = struct.unpack("<I", header)[0]
        if length > MAX_FRAME_BYTES:
            raise PipeError("pipe_read", f"frame too large: {length} bytes")
        payload = self._read_exact(length, deadline)
        try:
            frame = json.loads(payload.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise PipeError("pipe_read", f"invalid JSON frame: {exc}") from exc
        if not isinstance(frame, dict):
            raise PipeError("pipe_read", "protocol frame is not an object")
        return frame

    def _read_exact(self, size: int, deadline: float) -> bytes:
        try:
            import win32file
            import win32pipe
        except Exception as exc:
            raise PipeError("pipe_read", f"pywin32 is required: {exc}") from exc

        chunks: list[bytes] = []
        remaining = size
        while remaining > 0 and time.monotonic() < deadline:
            try:
                _buf, available, _left = win32pipe.PeekNamedPipe(self.handle, 0)
            except Exception as exc:
                raise PipeError("pipe_read", f"PeekNamedPipe failed: {exc}") from exc
            if available:
                read_size = min(remaining, available)
                _rc, data = win32file.ReadFile(self.handle, read_size)
                chunks.append(data)
                remaining -= len(data)
                continue
            time.sleep(0.02)
        if remaining:
            raise PipeError("pipe_read", f"timed out reading {size} bytes")
        return b"".join(chunks)

    @staticmethod
    def _normalize_response(frame: dict[str, Any]) -> dict[str, Any]:
        if frame.get("ok"):
            data = frame.get("data")
            if isinstance(data, dict):
                response = dict(data)
            else:
                response = {"data": data}
            response["_protocol_ok"] = True
            response["_frame"] = frame
            return response
        err = frame.get("err") if isinstance(frame.get("err"), dict) else {}
        return {
            "ok": False,
            "_protocol_ok": False,
            "error": err,
            "message": err.get("msg", "WinDbg MCP request failed"),
            "code": err.get("code", "unknown"),
            "tip": err.get("tip", ""),
            "_frame": frame,
        }
