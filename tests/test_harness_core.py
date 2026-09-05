from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "windows-drv-harness"
    / "scripts"
)
SPEC = importlib.util.spec_from_file_location("harness_core", SCRIPT_DIR / "harness_core.py")
assert SPEC and SPEC.loader
harness_core = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = harness_core
SPEC.loader.exec_module(harness_core)


class HarnessCoreTests(unittest.TestCase):
    def test_pipe_is_derived_per_target(self) -> None:
        self.assertEqual(harness_core.derived_pipe("win10-18362"), "windbgmcp-win10-18362")
        name, endpoint = harness_core.normalize_pipe("windbgmcp-win10-18362")
        self.assertEqual(name, "windbgmcp-win10-18362")
        self.assertEqual(endpoint, r"\\.\pipe\windbgmcp-win10-18362")

    def test_unsafe_pipe_is_rejected(self) -> None:
        with self.assertRaises(harness_core.HarnessError):
            harness_core.normalize_pipe(r"..\other")

    def test_legacy_config_migrates_to_one_target(self) -> None:
        migrated = harness_core.migrate_legacy_config(
            {
                "vm": {"vmx_path": "C:/vm/test.vmx", "baseline_snapshot": "base"},
                "guest": {"admin_user": "user", "admin_password": "secret"},
                "host": {"vmrun_path": "C:/tools/vmrun.exe"},
                "flags": {"baseline_snapshot_created": True},
            },
            "legacy",
        )
        self.assertEqual(migrated["version"], 2)
        self.assertEqual(migrated["default_target"], "legacy")
        self.assertEqual(migrated["targets"]["legacy"]["mcp_pipe"], "windbgmcp-legacy")

    def test_redact_never_returns_passwords_or_tokens(self) -> None:
        redacted = harness_core.redact(
            {"admin_password": "secret", "api_token": "token", "nested": {"value": 3}}
        )
        self.assertEqual(redacted["admin_password"], "***")
        self.assertEqual(redacted["api_token"], "***")
        self.assertEqual(redacted["nested"]["value"], 3)
        self.assertTrue(harness_core.redact({"password_present": True})["password_present"])

    def test_target_list_exposes_no_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "default_target": "one",
                        "host": {},
                        "targets": {
                            "one": {
                                "vmx_path": "C:/vm/one.vmx",
                                "baseline_snapshot": "base",
                                "kd_pipe": "kd-one",
                                "mcp_pipe": "windbgmcp-one",
                                "guest": {
                                    "admin_user": "user",
                                    "admin_password": "secret",
                                    "deploy_dir": "C:/deploy",
                                },
                            },
                            "two": {
                                "vmx_path": "D:/vm/two.vmx",
                                "baseline_snapshot": "base",
                                "kd_pipe": "kd-two",
                                "mcp_pipe": "windbgmcp-two",
                                "guest": {
                                    "admin_user": "user2",
                                    "admin_password": "secret2",
                                    "deploy_dir": "C:/deploy",
                                },
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            harness = harness_core.Harness(config_path, root)
            result = harness.list_targets()
            rendered = json.dumps(result)
            self.assertNotIn("secret", rendered)
            self.assertEqual([item["name"] for item in result["targets"]], ["one", "two"])
            self.assertNotEqual(
                result["targets"][0]["mcp_pipe"], result["targets"][1]["mcp_pipe"]
            )

    def test_explicit_host_tools_are_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            windbg = root / "windbg.exe"
            msbuild = root / "MSBuild.exe"
            windbg.write_bytes(b"")
            msbuild.write_bytes(b"")
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "default_target": "one",
                        "host": {
                            "windbg_path": str(windbg),
                            "msbuild_path": str(msbuild),
                        },
                        "targets": {
                            "one": {
                                "vmx_path": "C:/vm/one.vmx",
                                "baseline_snapshot": "base",
                                "kd_pipe": "kd-one",
                                "mcp_pipe": "windbgmcp-one",
                                "guest": {},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            harness = harness_core.Harness(config_path, root)
            self.assertEqual(harness._find_windbg(harness.config["host"]), str(windbg))
            self.assertEqual(harness._find_msbuild(harness.config["host"]), str(msbuild))


if __name__ == "__main__":
    unittest.main()
