#!/usr/bin/env python3
"""Create or update one target in the user-level harness config."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

from harness_core import CONFIG_VERSION, default_config_path, derived_pipe, migrate_legacy_config, normalize_pipe


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configure one Windows driver lab target")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--target", required=True)
    parser.add_argument("--vmx", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--guest-user", required=True)
    parser.add_argument("--guest-deploy-dir", required=True)
    parser.add_argument("--pipe")
    parser.add_argument("--kd-pipe")
    parser.add_argument("--vmrun")
    parser.add_argument("--vmmon")
    parser.add_argument("--windbg")
    parser.add_argument("--msbuild")
    parser.add_argument("--password-env", help="Store ${env:NAME} instead of prompting")
    parser.add_argument("--keep-password", action="store_true")
    parser.add_argument("--make-default", action="store_true")
    return parser.parse_args()


def read_existing(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": CONFIG_VERSION, "default_target": "", "host": {}, "targets": {}}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if "targets" not in data and "vm" in data:
        data = migrate_legacy_config(data)
    if data.get("version") != CONFIG_VERSION:
        raise ValueError(f"unsupported config version: {data.get('version')}")
    return data


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ns = parse_args()
    config = read_existing(ns.config)
    existing = config.setdefault("targets", {}).get(ns.target, {})
    existing_guest = existing.get("guest", {})

    if ns.password_env:
        if not ns.password_env.replace("_", "a").isalnum() or ns.password_env[0].isdigit():
            raise ValueError("--password-env must be an environment variable name")
        password = "${env:" + ns.password_env + "}"
    elif ns.keep_password and existing_guest.get("admin_password"):
        password = existing_guest["admin_password"]
    else:
        password = getpass.getpass("Guest administrator password: ")
        if not password:
            raise ValueError("guest password cannot be empty")

    pipe_name, _ = normalize_pipe(ns.pipe or existing.get("mcp_pipe") or derived_pipe(ns.target))
    kd_value = ns.kd_pipe or existing.get("kd_pipe", "")
    if not kd_value:
        raise ValueError("--kd-pipe is required for a new target")
    kd_pipe_name, _ = normalize_pipe(kd_value)
    config["version"] = CONFIG_VERSION
    config.setdefault("host", {})
    for key, value in (
        ("vmrun_path", ns.vmrun),
        ("vmmon64_path", ns.vmmon),
        ("windbg_path", ns.windbg),
        ("msbuild_path", ns.msbuild),
    ):
        if value:
            config["host"][key] = str(Path(value).resolve())

    config["targets"][ns.target] = {
        "vmx_path": str(Path(ns.vmx).resolve()),
        "baseline_snapshot": ns.snapshot,
        "mcp_pipe": pipe_name,
        "kd_pipe": kd_pipe_name,
        "guest": {
            "admin_user": ns.guest_user,
            "admin_password": password,
            "deploy_dir": ns.guest_deploy_dir,
            "arch": existing_guest.get("arch", "x64"),
        },
        "flags": {
            "baseline_debugger_attached": True,
        },
    }
    if ns.make_default or not config.get("default_target"):
        config["default_target"] = ns.target
    atomic_write(ns.config, config)
    print(
        json.dumps(
            {
                "ok": True,
                "status": "target_configured",
                "config_path": str(ns.config.resolve()),
                "target": ns.target,
                "mcp_pipe": pipe_name,
                "kd_pipe": kd_pipe_name,
                "guest_password": "***",
                "next_action": "Run setup-host.ps1, then harness_cli.py doctor.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
