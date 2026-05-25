#!/usr/bin/env python3
"""Client-independent MCP stdio smoke test.

This validates that a command launches, speaks MCP JSON-RPC over stdio, and
returns tools/list. It does not prove that any particular agent has registered
the server.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def read_json_line(proc: subprocess.Popen[str], timeout: float) -> dict:
    deadline = time.time() + timeout
    line = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        line = proc.stdout.readline() if proc.stdout else ""
        if line:
            return json.loads(line)
        time.sleep(0.05)
    stderr = proc.stderr.read() if proc.stderr else ""
    raise RuntimeError(f"no JSON response from MCP server. stderr={stderr!r}")


def send(proc: subprocess.Popen[str], payload: dict) -> None:
    if not proc.stdin:
        raise RuntimeError("server stdin is closed")
    proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    proc.stdin.flush()


def smoke(command: list[str], timeout: float) -> dict:
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    try:
        send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-smoke-test", "version": "1.0"},
                },
            },
        )
        initialize = read_json_line(proc, timeout)
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = read_json_line(proc, timeout)
        tool_names = [
            item.get("name", "")
            for item in tools.get("result", {}).get("tools", [])
            if isinstance(item, dict)
        ]
        return {
            "ok": True,
            "command": command,
            "initialize_ok": "result" in initialize,
            "tool_count": len(tool_names),
            "tool_names": tool_names,
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def default_command(name: str) -> list[str]:
    skill_dir = Path(__file__).resolve().parents[1]
    if name == "windbg":
        return [str(skill_dir / "windbg-mcp" / "windbg-mcp.exe")]
    if name == "vmware":
        return [str(skill_dir / "vmware-mcp" / ".venv" / "Scripts" / "vmware-mcp.exe")]
    raise ValueError(f"unknown default server: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test an MCP stdio server.")
    parser.add_argument("--server", choices=["windbg", "vmware"], help="Use a bundled server command.")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Custom command after --")
    ns = parser.parse_args()

    if ns.server:
        command = default_command(ns.server)
    else:
        command = ns.command
        if command and command[0] == "--":
            command = command[1:]
    if not command:
        parser.error("provide --server or a command after --")

    result = smoke(command, ns.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
