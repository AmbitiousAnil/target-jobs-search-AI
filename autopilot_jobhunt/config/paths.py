from __future__ import annotations

from pathlib import Path

from .text import stripped_env


def get_pilot_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_repo_root() -> Path:
    return get_pilot_root()


def get_runtime_root() -> Path:
    override = stripped_env("JOBHUNT_ADK_RUNTIME_ROOT")
    if override:
        return Path(override).resolve()
    return get_pilot_root() / "runtime"


def get_session_root() -> Path:
    return get_runtime_root() / "sessions"

