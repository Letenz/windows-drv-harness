"""Configuration helpers for driver-harness-mcp tools."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


ENV_REF_RE = re.compile(r"^\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}$")


def repo_root() -> Path:
    """Return the repository root when running from the in-repo package layout."""
    return Path(__file__).resolve().parents[3]


def default_config_path() -> Path:
    return repo_root() / "driver-harness.config.json"


def resolve_env_refs(value: Any) -> Any:
    """Resolve ${env:VAR} strings recursively."""
    if isinstance(value, dict):
        return {k: resolve_env_refs(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_env_refs(v) for v in value]
    if isinstance(value, str):
        match = ENV_REF_RE.match(value.strip())
        if match:
            return os.environ.get(match.group(1), "")
    return value


def load_config(config_path: str | None = None, *, required: bool = False) -> dict[str, Any]:
    """Load the user config, resolving environment references.

    Args:
        config_path: Optional path. Defaults to repo-root driver-harness.config.json.
        required: Raise FileNotFoundError if the config is absent.
    """
    path = Path(config_path) if config_path else default_config_path()
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"driver harness config not found: {path}")
        return {}

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return resolve_env_refs(data)


def config_value(config: dict[str, Any], dotted_key: str, default: str = "") -> str:
    cur: Any = config
    for part in dotted_key.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
    if cur is None:
        return default
    return str(cur)


def config_bool(config: dict[str, Any], dotted_key: str, default: bool = False) -> bool:
    cur: Any = config
    for part in dotted_key.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
    if cur is None:
        return default
    if isinstance(cur, bool):
        return cur
    if isinstance(cur, (int, float)):
        return bool(cur)
    if isinstance(cur, str):
        return cur.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def first_existing_path(*paths: str | os.PathLike[str] | None) -> str:
    for value in paths:
        if not value:
            continue
        path = Path(str(value))
        if path.exists():
            return str(path)
    return ""
