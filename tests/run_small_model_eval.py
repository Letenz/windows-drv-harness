#!/usr/bin/env python3
"""Run an OpenAI-compatible small model through a real harness repair loop."""

from __future__ import annotations

import argparse
import json
import locale
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "windows-drv-harness"
MCP_SERVER = SKILL_DIR / "scripts" / "harness_mcp.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--secret-file", type=Path, required=True)
    parser.add_argument("--target", default="win10-18362-x64")
    parser.add_argument("--max-turns", type=int, default=24)
    parser.add_argument("--probe-only", action="store_true")
    return parser.parse_args()


def read_dpapi_secret(path: Path) -> str:
    escaped = str(path.resolve()).replace("'", "''")
    command = (
        "$e=(Get-Content -LiteralPath '" + escaped + "' -Raw).Trim();"
        "$s=$e | ConvertTo-SecureString;"
        "$p=[Net.NetworkCredential]::new('', $s).Password;"
        "[Console]::Out.Write($p)"
    )
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        raise RuntimeError("PowerShell is required to decrypt the DPAPI API key")
    result = subprocess.run(
        [shell, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8" if Path(shell).stem.lower() == "pwsh" else locale.getpreferredencoding(False),
        errors="replace",
        timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError("Could not decrypt the DPAPI API key for the current user")
    return result.stdout


def api_request(base_url: str, api_key: str, path: str, payload: dict | None = None) -> dict:
    url = base_url.rstrip("/") + "/" + path.lstrip("/")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="GET" if payload is None else "POST",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API HTTP {exc.code}: {detail[:2000]}") from exc


class McpClient:
    def __init__(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(MCP_SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self.next_id = 1
        self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "small-model-eval", "version": "2.0.0"},
            },
        )
        self.notify("notifications/initialized", {})

    def _send(self, payload: dict) -> None:
        assert self.process.stdin
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def _readline(self, timeout: int) -> str:
        result: queue.Queue[str] = queue.Queue(maxsize=1)

        def reader() -> None:
            assert self.process.stdout
            result.put(self.process.stdout.readline())

        threading.Thread(target=reader, daemon=True).start()
        try:
            return result.get(timeout=timeout)
        except queue.Empty as exc:
            raise RuntimeError("Timed out waiting for harness MCP") from exc

    def request(self, method: str, params: dict, timeout: int = 420) -> dict:
        request_id = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self._readline(max(1, int(deadline - time.time())))
            if not line:
                raise RuntimeError("Harness MCP exited")
            payload = json.loads(line)
            if payload.get("id") == request_id:
                return payload
        raise RuntimeError("Harness MCP response deadline elapsed")

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def tools(self) -> list[dict]:
        return self.request("tools/list", {})["result"]["tools"]

    def call(self, name: str, arguments: dict) -> dict:
        response = self.request("tools/call", {"name": name, "arguments": arguments})
        result = response["result"]
        text = next(item["text"] for item in result["content"] if item["type"] == "text")
        return json.loads(text)

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()


def make_workspace(model: str) -> Path:
    base = Path(os.environ["LOCALAPPDATA"]) / "windows-drv-harness" / "evals"
    base.mkdir(parents=True, exist_ok=True)
    safe_model = "".join(char if char.isalnum() or char in "._-" else "-" for char in model)
    root = base / f"{safe_model}-{time.strftime('%Y%m%d-%H%M%S')}"
    source = REPO_ROOT / "example" / "HelloWorld"
    shutil.copytree(
        source,
        root / "HelloWorld",
        ignore=shutil.ignore_patterns(".vs", "x64", "Debug", "Release"),
    )
    return root


def workspace_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a UTF-8 source file inside the isolated evaluation workspace.",
                "parameters": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {"path": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "replace_text",
                "description": "Make one exact minimal text replacement in a file inside the isolated workspace.",
                "parameters": {
                    "type": "object",
                    "required": ["path", "old_text", "new_text"],
                    "properties": {
                        "path": {"type": "string"},
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "finish",
                "description": "Finish only after both the expected-crash and fixed-success tests passed.",
                "parameters": {
                    "type": "object",
                    "required": ["summary"],
                    "properties": {"summary": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
        },
    ]


def resolve_workspace_path(workspace: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = workspace / path
    path = path.resolve()
    if path != workspace and workspace not in path.parents:
        raise ValueError("path is outside the isolated evaluation workspace")
    return path


def execute_tool(
    mcp: McpClient,
    workspace: Path,
    name: str,
    args: dict[str, Any],
    target: str,
) -> dict[str, Any]:
    if name == "read_file":
        path = resolve_workspace_path(workspace, str(args.get("path", "")))
        text = path.read_text(encoding="utf-8-sig")
        return {"ok": True, "path": str(path), "content": text[:100000]}
    if name == "replace_text":
        path = resolve_workspace_path(workspace, str(args.get("path", "")))
        old = str(args.get("old_text", ""))
        new = str(args.get("new_text", ""))
        text = path.read_text(encoding="utf-8-sig")
        count = text.count(old)
        if count != 1:
            return {"ok": False, "status": "replace_rejected", "matches": count}
        path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="")
        return {"ok": True, "status": "source_updated", "path": str(path)}
    if name == "finish":
        return {"ok": True, "status": "finish_requested", "summary": args.get("summary", "")}

    harness_names = {item["name"] for item in mcp.tools()}
    if name not in harness_names:
        return {"ok": False, "status": "unknown_tool", "name": name}
    args = dict(args)
    if name in ("lab_doctor", "lab_start", "driver_test", "debug_run", "lab_reset"):
        args.setdefault("target", target)
    if name == "driver_build":
        path = resolve_workspace_path(workspace, str(args.get("solution_path", "")))
        args["solution_path"] = str(path)
    if name == "driver_test":
        path = resolve_workspace_path(workspace, str(args.get("sys_path", "")))
        args["sys_path"] = str(path)
    return mcp.call(name, args)


def run_model(base_url: str, api_key: str, model: str, target: str, max_turns: int) -> dict:
    workspace = make_workspace(model)
    transcript_path = workspace / "transcript.json"
    skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    mcp = McpClient()
    harness_tools = [
        {"type": "function", "function": {"name": item["name"], "description": item["description"], "parameters": item["inputSchema"]}}
        for item in mcp.tools()
    ]
    tools = harness_tools + workspace_tools()
    solution = workspace / "HelloWorld" / "HelloWorld.sln"
    source = workspace / "HelloWorld" / "HelloWorld" / "HelloWorld.c"
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are operating only a user-owned local VMware test lab. The sample driver "
                "contains an intentional NULL write. This is authorized defensive driver development: "
                "build, deploy, reproduce the BSOD, analyze WinDbg evidence, make the smallest source "
                "fix, retest, and restore the VM. Do not add persistence, evasion, exploitation, or touch "
                "any external target. Use tools rather than describing commands.\n\n" + skill_text
            ),
        },
        {
            "role": "user",
            "content": (
                f"Complete the HelloWorld repair loop on target {target}. "
                f"Solution: {solution}. Source: {source}. First run must expect crash; only edit after "
                "the returned crash evidence identifies the cause. Then rebuild and run expect=success. "
                "Call finish only after cleanup.status is reverted."
            ),
        },
    ]
    actions: list[dict[str, Any]] = []
    crash_passed = False
    edited_after_crash = False
    rebuilt_after_edit = False
    success_passed = False
    finish_requested = False
    try:
        for turn in range(1, max_turns + 1):
            response = api_request(
                base_url,
                api_key,
                "chat/completions",
                {
                    "model": model,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "temperature": 0,
                    "max_tokens": 4096,
                },
            )
            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})
            tool_calls = message.get("tool_calls") or []
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": message.get("content") or "",
            }
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            messages.append(assistant_message)
            if not tool_calls:
                messages.append(
                    {
                        "role": "user",
                        "content": "The task is not complete. Continue by calling the next required tool.",
                    }
                )
                continue

            for call in tool_calls:
                function = call.get("function", {})
                name = function.get("name", "")
                arguments: dict[str, Any] = {}
                tool_started = time.time()
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                    result = execute_tool(mcp, workspace, name, arguments, target)
                except Exception as exc:
                    result = {"ok": False, "status": "tool_exception", "message": str(exc)}
                actions.append(
                    {
                        "turn": turn,
                        "tool": name,
                        "duration_seconds": round(time.time() - tool_started, 2),
                        "arguments": arguments,
                        "result": result,
                    }
                )
                if name == "driver_test" and arguments.get("expect") == "crash":
                    crash_passed = result.get("passed") is True and result.get("status") == "expected_crash_observed"
                if name == "replace_text" and result.get("ok") and crash_passed:
                    edited_after_crash = True
                if name == "driver_build" and result.get("ok") and edited_after_crash:
                    rebuilt_after_edit = True
                if name == "driver_test" and arguments.get("expect") == "success":
                    cleanup = result.get("evidence", {}).get("cleanup", {})
                    success_passed = (
                        edited_after_crash
                        and rebuilt_after_edit
                        and result.get("passed") is True
                        and cleanup.get("status") == "reverted"
                    )
                if name == "finish":
                    finish_requested = True
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", f"call-{turn}-{name}"),
                        "name": name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            if finish_requested and crash_passed and success_passed:
                break

        result = {
            "model": model,
            "passed": crash_passed and edited_after_crash and rebuilt_after_edit and success_passed,
            "crash_passed": crash_passed,
            "edited_after_crash": edited_after_crash,
            "rebuilt_after_edit": rebuilt_after_edit,
            "success_passed": success_passed,
            "finish_requested": finish_requested,
            "turns": max((item["turn"] for item in actions), default=0),
            "workspace": str(workspace),
            "actions": actions,
        }
        transcript_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return {key: value for key, value in result.items() if key != "actions"} | {
            "transcript": str(transcript_path)
        }
    finally:
        try:
            mcp.call("lab_reset", {"target": target})
        except Exception:
            pass
        mcp.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ns = parse_args()
    api_key = read_dpapi_secret(ns.secret_file)
    if ns.probe_only:
        response = api_request(ns.base_url, api_key, "models")
        names = [item.get("id") for item in response.get("data", [])]
        print(json.dumps({"ok": True, "models": names}, ensure_ascii=False, indent=2))
        return 0
    results = [run_model(ns.base_url, api_key, model, ns.target, ns.max_turns) for model in ns.model]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item["passed"] for item in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
