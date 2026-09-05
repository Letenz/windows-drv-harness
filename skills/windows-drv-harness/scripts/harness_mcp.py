#!/usr/bin/env python3
"""Small-model-oriented stdio MCP server for the driver harness."""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from harness_core import Harness, HarnessError, redact


SERVER_VERSION = "2.0.0"


TOOLS = [
    {
        "name": "lab_list_targets",
        "description": "List configured VM targets. Start here when the target name is unknown.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "lab_doctor",
        "description": "Check one target without changing the VM. Follow next_action exactly.",
        "inputSchema": {
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "lab_start",
        "description": "Restore and start one target, bind a unique VirtualKD pipe, launch WinDbg, and verify the debugger session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "timeout_seconds": {"type": "integer", "minimum": 30, "maximum": 300},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "driver_build",
        "description": "Build a Windows driver with an MSBuild version compatible with the installed WDK and return the generated .sys path.",
        "inputSchema": {
            "type": "object",
            "required": ["solution_path"],
            "properties": {
                "solution_path": {"type": "string"},
                "configuration": {"type": "string", "default": "Debug"},
                "platform": {"type": "string", "default": "x64"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "driver_test",
        "description": "Run a complete driver load test and always restore the target baseline. Use expect=crash before fixing a seeded bug and expect=success after rebuilding.",
        "inputSchema": {
            "type": "object",
            "required": ["sys_path", "service_name", "expect"],
            "properties": {
                "target": {"type": "string"},
                "sys_path": {"type": "string", "description": "Absolute host path to the built .sys file."},
                "service_name": {"type": "string"},
                "expect": {"type": "string", "enum": ["crash", "success"]},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "debug_run",
        "description": "Run one targeted WinDbg command against a running target session. Use only when driver_test evidence is insufficient.",
        "inputSchema": {
            "type": "object",
            "required": ["command"],
            "properties": {
                "target": {"type": "string"},
                "command": {"type": "string"},
                "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 120000},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "lab_reset",
        "description": "Stop only the selected target session and restore its configured baseline snapshot.",
        "inputSchema": {
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "additionalProperties": False,
        },
    },
]


def tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    harness = Harness()
    target = args.get("target")
    handlers: dict[str, Callable[[], dict[str, Any]]] = {
        "lab_list_targets": harness.list_targets,
        "lab_doctor": lambda: harness.doctor(target),
        "lab_start": lambda: harness.start(target, int(args.get("timeout_seconds", 120))),
        "driver_build": lambda: harness.driver_build(
            str(args.get("solution_path", "")),
            str(args.get("configuration", "Debug")),
            str(args.get("platform", "x64")),
        ),
        "driver_test": lambda: harness.driver_test(
            target,
            str(args.get("sys_path", "")),
            str(args.get("service_name", "")),
            str(args.get("expect", "")),
        ),
        "debug_run": lambda: harness.debug_run(
            target,
            str(args.get("command", "")),
            int(args.get("timeout_ms", 30000)),
        ),
        "lab_reset": lambda: harness.reset(target),
    }
    if name not in handlers:
        raise HarnessError(
            "tool_unknown",
            f"Unknown harness tool: {name}",
            "Call tools/list and use an exact tool name.",
        )
    return handlers[name]()


def response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def text_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(redact(payload), ensure_ascii=False, separators=(",", ":")),
            }
        ],
        "isError": not bool(payload.get("ok")),
    }


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        requested = message.get("params", {}).get("protocolVersion", "2024-11-05")
        return response(
            request_id,
            {
                "protocolVersion": requested,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "windows-drv-harness", "version": SERVER_VERSION},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return response(request_id, {})
    if method == "tools/list":
        return response(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params", {})
        name = str(params.get("name", ""))
        args = params.get("arguments") or {}
        try:
            payload = tool_call(name, args)
        except HarnessError as exc:
            payload = exc.result(args.get("target"))
        except Exception as exc:
            payload = {
                "ok": False,
                "status": "failed",
                "error_code": "internal_error",
                "message": str(exc),
                "next_action": "Run lab_doctor and report this error if it repeats.",
            }
        return response(request_id, text_result(payload))
    if request_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return None


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    for line in sys.stdin:
        try:
            message = json.loads(line)
            answer = handle(message)
            if answer is not None:
                sys.stdout.write(json.dumps(answer, separators=(",", ":")) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            sys.stderr.write(f"windows-drv-harness: {exc}\n")
            sys.stderr.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
