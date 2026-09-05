#!/usr/bin/env python3
"""Human/CI command-line entrypoint for the driver harness core."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from harness_core import Harness, HarnessError, redact


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Windows driver harness v2")
    root.add_argument("--config", help="Override the user config path.")
    commands = root.add_subparsers(dest="action", required=True)
    commands.add_parser("list-targets")

    doctor = commands.add_parser("doctor")
    doctor.add_argument("--target")

    start = commands.add_parser("start")
    start.add_argument("--target")
    start.add_argument("--timeout", type=int, default=120)

    build = commands.add_parser("build-driver")
    build.add_argument("--solution", required=True)
    build.add_argument("--configuration", default="Debug")
    build.add_argument("--platform", default="x64")

    test = commands.add_parser("test-driver")
    test.add_argument("--target")
    test.add_argument("--sys", required=True, dest="sys_path")
    test.add_argument("--service", required=True)
    test.add_argument("--expect", choices=("crash", "success"), required=True)

    debug = commands.add_parser("debug")
    debug.add_argument("--target")
    debug.add_argument("--command", required=True, dest="debug_command")
    debug.add_argument("--timeout-ms", type=int, default=30000)

    reset = commands.add_parser("reset")
    reset.add_argument("--target")
    return root


def run(ns: argparse.Namespace) -> dict[str, Any]:
    harness = Harness(ns.config)
    if ns.action == "list-targets":
        return harness.list_targets()
    if ns.action == "doctor":
        return harness.doctor(ns.target)
    if ns.action == "start":
        return harness.start(ns.target, ns.timeout)
    if ns.action == "build-driver":
        return harness.driver_build(ns.solution, ns.configuration, ns.platform)
    if ns.action == "test-driver":
        return harness.driver_test(ns.target, ns.sys_path, ns.service, ns.expect)
    if ns.action == "debug":
        return harness.debug_run(ns.target, ns.debug_command, ns.timeout_ms)
    if ns.action == "reset":
        return harness.reset(ns.target)
    raise AssertionError(ns.action)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ns = parser().parse_args()
    try:
        result = run(ns)
    except HarnessError as exc:
        result = exc.result(getattr(ns, "target", None))
    print(json.dumps(redact(result), ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
