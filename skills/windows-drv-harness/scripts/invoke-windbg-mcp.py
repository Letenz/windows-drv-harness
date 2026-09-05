#!/usr/bin/env python3
"""One-shot JSON-RPC client for the bundled windbg-mcp.exe."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def read_json_line(proc: subprocess.Popen[str]) -> dict:
    line = proc.stdout.readline() if proc.stdout else ""
    if not line:
        stderr = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"windbg-mcp produced no response. stderr={stderr!r}")
    return json.loads(line)


def send(proc: subprocess.Popen[str], payload: dict) -> None:
    if not proc.stdin:
        raise RuntimeError("windbg-mcp stdin is closed")
    proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    proc.stdin.flush()


def call_tool(server: Path, pipe: str | None, tool: str, arguments: dict) -> dict:
    command = [str(server)]
    if pipe:
        command += ["--pipe", pipe]
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
                    "clientInfo": {
                        "name": "windows-drv-harness-script",
                        "version": "1.0",
                    },
                },
            },
        )
        read_json_line(proc)

        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            },
        )
        return read_json_line(proc)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def build_arguments(tool: str, raw_json: str | None, raw_args: list[str]) -> dict:
    if raw_json:
        parsed = json.loads(raw_json)
        if not isinstance(parsed, dict):
            raise ValueError("--json must decode to an object")
        return parsed
    if not raw_args:
        return {}
    value = " ".join(raw_args)
    if tool == "wm_run_cmd":
        return {"cmd": value}
    return {"name": value}


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    default_server = skill_dir / "windbg-mcp" / "windbg-mcp.exe"

    parser = argparse.ArgumentParser(
        description="Call one bundled windbg-mcp tool and print the JSON response."
    )
    parser.add_argument("tool", help="Tool name, e.g. wm_session or wm_run_cmd")
    parser.add_argument("args", nargs="*", help="Plain argument. For wm_run_cmd this becomes cmd.")
    parser.add_argument("--json", help="Tool arguments as a JSON object.")
    parser.add_argument("--server", default=str(default_server), help="Path to windbg-mcp.exe.")
    parser.add_argument("--pipe", help="Target-specific pipe name or endpoint.")
    ns = parser.parse_args()

    arguments = build_arguments(ns.tool, ns.json, ns.args)
    response = call_tool(Path(ns.server), ns.pipe, ns.tool, arguments)
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
