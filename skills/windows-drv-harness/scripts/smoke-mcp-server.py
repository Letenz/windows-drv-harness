#!/usr/bin/env python3
"""Protocol smoke test for bundled stdio MCP servers."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from pathlib import Path


def read_line(process: subprocess.Popen[str], timeout: float) -> str:
    result: list[str] = []

    def reader() -> None:
        result.append(process.stdout.readline() if process.stdout else "")

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive() or not result or not result[0]:
        raise RuntimeError("MCP server returned no JSON line")
    return result[0]


def send(process: subprocess.Popen[str], payload: dict) -> None:
    assert process.stdin
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()


def command_for(server: str, pipe: str | None) -> list[str]:
    skill = Path(__file__).resolve().parents[1]
    if server == "harness":
        return [sys.executable, str(skill / "scripts" / "harness_mcp.py")]
    if server == "windbg":
        native = skill / "windbg-mcp" / "windbg-mcp-v2.exe"
        if not native.is_file():
            native = skill / "windbg-mcp" / "windbg-mcp.exe"
        command = [str(native)]
        if pipe:
            command += ["--pipe", pipe]
        return command
    executable = skill / "vmware-mcp" / ".venv" / "Scripts" / "vmware-mcp.exe"
    return [str(executable)]


def smoke(command: list[str], timeout: float) -> dict:
    process = subprocess.Popen(
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
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-smoke", "version": "2.0.0"},
                },
            },
        )
        initialize = json.loads(read_line(process, timeout))
        send(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        send(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = json.loads(read_line(process, timeout))
        names = [item.get("name") for item in tools.get("result", {}).get("tools", [])]
        return {
            "ok": bool(initialize.get("result")) and bool(names),
            "command": command,
            "server": initialize.get("result", {}).get("serverInfo", {}),
            "tool_count": len(names),
            "tools": names,
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", choices=("harness", "windbg", "vmware"), required=True)
    parser.add_argument("--pipe", help="Optional windbg-mcp endpoint")
    parser.add_argument("--timeout", type=float, default=10.0)
    ns = parser.parse_args()
    result = smoke(command_for(ns.server, ns.pipe), ns.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
