from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re
import uuid
from collections.abc import MutableMapping
from typing import Any

from job_hunt.config_utils import sanitize_nested_strings

from ..app_paths import get_session_root
from .session_files import JobSearchConfiguration, StagedSession


CONFIG_STATE_KEY = "jobhunt_configuration"
INTERNAL_CONFIG_STATE_KEY = "jobhunt_configuration_internal"
SUMMARY_STATE_KEY = "jobhunt_configuration_summary"
SESSION_DIR_STATE_KEY = "jobhunt_session_dir"
RESCAN_REQUIRED_STATE_KEY = "jobhunt_rescan_required"
CONFIG_CHANGE_SUMMARY_STATE_KEY = "jobhunt_config_change_summary"
DISK_STATE_FILE_NAME = "session_state.json"


def _extract_state(tool_context: Any | None) -> MutableMapping[str, Any] | None:
    if tool_context is None:
        return None

    direct_state = getattr(tool_context, "state", None)
    if isinstance(direct_state, MutableMapping):
        return direct_state

    session = getattr(tool_context, "session", None)
    session_state = getattr(session, "state", None)
    if isinstance(session_state, MutableMapping):
        return session_state

    invocation_context = getattr(tool_context, "invocation_context", None)
    invocation_session = getattr(invocation_context, "session", None)
    invocation_state = getattr(invocation_session, "state", None)
    if isinstance(invocation_state, MutableMapping):
        return invocation_state

    return None


def _slugify_session_id(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "session"


def _peek_session_id(tool_context: Any | None) -> str | None:
    for candidate in (
        getattr(tool_context, "session_id", None),
        getattr(getattr(tool_context, "session", None), "id", None),
        getattr(getattr(tool_context, "invocation_context", None), "session_id", None),
        getattr(getattr(getattr(tool_context, "invocation_context", None), "session", None), "id", None),
    ):
        if candidate:
            return str(candidate)

    state = _extract_state(tool_context)
    if state is not None and state.get("jobhunt_session_id"):
        return str(state["jobhunt_session_id"])

    return None


def _session_dir_from_tool_context(tool_context: Any | None) -> Path | None:
    state = _extract_state(tool_context)
    if state is not None:
        session_dir = state.get(SESSION_DIR_STATE_KEY)
        if isinstance(session_dir, str) and session_dir.strip():
            return Path(session_dir)

    session_id = _peek_session_id(tool_context)
    if not session_id:
        return None

    return get_session_root() / _slugify_session_id(session_id)


def _disk_state_path_from_session_dir(session_dir: Path) -> Path:
    return session_dir / DISK_STATE_FILE_NAME


def _load_disk_state(tool_context: Any | None) -> dict[str, Any] | None:
    session_dir = _session_dir_from_tool_context(tool_context)
    if session_dir is None:
        return None

    state_path = _disk_state_path_from_session_dir(session_dir)
    if not state_path.exists():
        return None

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    return sanitize_nested_strings(payload) if isinstance(payload, dict) else None


def _write_disk_state(session_dir: Path, payload: dict[str, Any]) -> None:
    state_path = _disk_state_path_from_session_dir(session_dir)
    state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _build_persisted_state_payload(
    config: JobSearchConfiguration,
    staged: StagedSession,
    *,
    rescan_required: bool,
    config_change_summary: str | None,
) -> dict[str, Any]:
    return {
        "jobhunt_session_id": staged.session_id,
        CONFIG_STATE_KEY: config.public_summary()
        | {
            "session_dir": str(staged.session_dir),
            "rescan_required": rescan_required,
        },
        INTERNAL_CONFIG_STATE_KEY: asdict(config),
        SUMMARY_STATE_KEY: (
            f"roles={', '.join(config.target_roles)} | "
            f"locations={', '.join(config.target_locations)} | "
            f"companies={len(config.company_urls)} | "
            f"direct_jobs={len(config.job_urls)} | "
            f"min_score={config.min_score} | top_n={config.top_n}"
        ),
        SESSION_DIR_STATE_KEY: str(staged.session_dir),
        RESCAN_REQUIRED_STATE_KEY: rescan_required,
        CONFIG_CHANGE_SUMMARY_STATE_KEY: config_change_summary or "",
    }


def get_or_create_session_id(tool_context: Any | None) -> str:
    candidate = _peek_session_id(tool_context)
    if candidate:
        return candidate

    state = _extract_state(tool_context)
    session_id = f"manual-{uuid.uuid4().hex[:12]}"
    if state is not None:
        state["jobhunt_session_id"] = session_id
    return session_id


def persist_session_configuration(
    tool_context: Any | None,
    config: JobSearchConfiguration,
    staged: StagedSession,
    *,
    rescan_required: bool = True,
    config_change_summary: str | None = None,
) -> None:
    state = _extract_state(tool_context)
    payload = _build_persisted_state_payload(
        config,
        staged,
        rescan_required=rescan_required,
        config_change_summary=config_change_summary,
    )
    if state is not None:
        state.update(payload)
    _write_disk_state(staged.session_dir, payload)


def load_session_configuration(tool_context: Any | None) -> dict | None:
    state = _extract_state(tool_context)
    config = state.get(CONFIG_STATE_KEY) if state is not None else None
    if isinstance(config, dict):
        return config

    disk_state = _load_disk_state(tool_context)
    if disk_state is None:
        return None
    config = disk_state.get(CONFIG_STATE_KEY)
    if isinstance(config, dict):
        return config
    return None


def load_internal_session_configuration(tool_context: Any | None) -> dict | None:
    state = _extract_state(tool_context)
    config = state.get(INTERNAL_CONFIG_STATE_KEY) if state is not None else None
    if isinstance(config, dict):
        return config

    disk_state = _load_disk_state(tool_context)
    if disk_state is None:
        return None
    config = disk_state.get(INTERNAL_CONFIG_STATE_KEY)
    if isinstance(config, dict):
        return config
    return None


def load_rescan_required(tool_context: Any | None) -> bool:
    state = _extract_state(tool_context)
    if state is not None and RESCAN_REQUIRED_STATE_KEY in state:
        return bool(state.get(RESCAN_REQUIRED_STATE_KEY, True))

    disk_state = _load_disk_state(tool_context)
    if disk_state is None:
        return True
    return bool(disk_state.get(RESCAN_REQUIRED_STATE_KEY, True))


def load_config_change_summary(tool_context: Any | None) -> str | None:
    state = _extract_state(tool_context)
    summary = state.get(CONFIG_CHANGE_SUMMARY_STATE_KEY) if state is not None else None
    if isinstance(summary, str) and summary.strip():
        return summary

    disk_state = _load_disk_state(tool_context)
    if disk_state is None:
        return None
    summary = disk_state.get(CONFIG_CHANGE_SUMMARY_STATE_KEY)
    if isinstance(summary, str) and summary.strip():
        return summary
    return None


def update_rescan_state(
    tool_context: Any | None,
    *,
    rescan_required: bool,
    config_change_summary: str | None = None,
) -> None:
    state = _extract_state(tool_context)
    if state is not None:
        state[RESCAN_REQUIRED_STATE_KEY] = rescan_required
        if config_change_summary is not None:
            state[CONFIG_CHANGE_SUMMARY_STATE_KEY] = config_change_summary

        config = state.get(CONFIG_STATE_KEY)
        if isinstance(config, dict):
            config["rescan_required"] = rescan_required

    disk_state = _load_disk_state(tool_context)
    session_dir = _session_dir_from_tool_context(tool_context)
    if disk_state is None or session_dir is None:
        return

    disk_state[RESCAN_REQUIRED_STATE_KEY] = rescan_required
    if config_change_summary is not None:
        disk_state[CONFIG_CHANGE_SUMMARY_STATE_KEY] = config_change_summary

    config = disk_state.get(CONFIG_STATE_KEY)
    if isinstance(config, dict):
        config["rescan_required"] = rescan_required

    _write_disk_state(session_dir, disk_state)
