from __future__ import annotations

import json
import os
from pathlib import Path

from job_hunt.config_utils import sanitize_nested_strings, stripped_env


def get_pilot_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_repo_root() -> Path:
    return get_pilot_root()


def load_repo_config() -> dict:
    repo_root = get_repo_root()
    config_path = repo_root / "config.json"
    if not config_path.exists():
        config_path = repo_root / "config.example.json"
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return sanitize_nested_strings(payload) if isinstance(payload, dict) else {}


def get_runtime_root() -> Path:
    override = stripped_env("JOBHUNT_ADK_RUNTIME_ROOT")
    if override:
        return Path(override).resolve()
    return get_pilot_root() / "runtime"


def get_session_root() -> Path:
    return get_runtime_root() / "sessions"
