from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..config.loader import resolve_tinyfish_api_key
from ..config.text import sanitize_nested_strings
from ..domain.models import JobSearchConfiguration, StagedSession
from ..storage.scan_state import LAST_SCAN_FILE_NAME, RAW_JOBS_FILE_NAME
from ..storage.session_files import stage_session_files
from ..storage.session_state import (
    get_or_create_session_id,
    load_internal_session_configuration,
    load_session_configuration,
    persist_session_configuration,
)


def public_session_payload(staged: StagedSession) -> dict:
    return {
        "session_id": staged.session_id,
        "session_dir": str(staged.session_dir),
        "config_path": str(staged.config_path),
        "companies_path": str(staged.companies_path),
        "resume_path": str(staged.resume_path),
        "output_dir": str(staged.output_dir),
    }


def load_staged_session(tool_context: Any | None) -> StagedSession:
    configuration = load_session_configuration(tool_context)
    if not configuration:
        raise RuntimeError("This session is not configured yet. Use configure_candidate_search first.")
    session_id = get_or_create_session_id(tool_context)
    session_dir = Path(configuration["session_dir"])
    return StagedSession(
        session_id=session_id,
        session_dir=session_dir,
        resume_path=session_dir / "resume.md",
        companies_path=session_dir / "companies.json",
        config_path=session_dir / "config.json",
        manifest_path=session_dir / "manifest.json",
        state_dir=session_dir / "state",
        output_dir=session_dir / "output",
    )


def has_cached_scan(staged: StagedSession) -> bool:
    return (staged.state_dir / LAST_SCAN_FILE_NAME).exists()


def has_raw_jobs(staged: StagedSession) -> bool:
    return (staged.state_dir / RAW_JOBS_FILE_NAME).exists()


def scan_input_payload(config: dict) -> dict:
    return {
        "resume_text": str(config.get("resume_text") or "").strip(),
        "company_urls": list(config.get("company_urls") or []),
        "target_roles": list(config.get("target_roles") or []),
        "target_locations": list(config.get("target_locations") or []),
        "llm_provider_override": config.get("llm_provider_override"),
    }


def classify_configuration_change(previous: dict | None, current: JobSearchConfiguration) -> tuple[bool, str]:
    current_payload = asdict(current)
    if not previous:
        return True, "Saved a new configuration. Run scouting and evaluation."
    if scan_input_payload(previous) != scan_input_payload(current_payload):
        return True, "Updated scan inputs. Run scouting again before evaluation."
    previous_min_score = int(previous.get("min_score") or current.min_score)
    previous_top_n = int(previous.get("top_n") or current.top_n)
    if previous_min_score != current.min_score or previous_top_n != current.top_n:
        return False, "Updated threshold or ranking settings. Reuse discovered jobs and rerank the results."
    return False, "Configuration is unchanged. Reuse the latest discovered and scored jobs."


def configure_session(tool_context: Any | None, config: JobSearchConfiguration) -> dict:
    session_id = get_or_create_session_id(tool_context)
    previous_internal = load_internal_session_configuration(tool_context)
    staged = stage_session_files(session_id, config)
    validated = JobSearchConfiguration(**(json.loads(json.dumps(asdict(config)))))
    scan_input_changed, config_change_summary = classify_configuration_change(previous_internal, validated)
    cached_scan_exists = has_cached_scan(staged)
    rescan_required = scan_input_changed or not has_raw_jobs(staged)
    if not has_raw_jobs(staged) and not scan_input_changed:
        config_change_summary = "Updated threshold or ranking settings, but no discovered jobs are cached yet. Run scouting before evaluation."
    persist_session_configuration(tool_context, validated, staged, rescan_required=rescan_required, config_change_summary=config_change_summary)
    response = {
        "status": "success",
        "message": "Candidate search configuration saved. Run scouting next." if rescan_required else "Candidate search configuration updated. Cached jobs can be reused.",
        "configuration": validated.public_summary(),
        "session": public_session_payload(staged),
        "next_step": "scan_company_jobs" if rescan_required else "score_and_rank_jobs",
        "scan_reuse": {
            "rescan_required": rescan_required,
            "cached_discovered_jobs_available": has_raw_jobs(staged),
            "cached_scored_results_available": cached_scan_exists,
            "reason": config_change_summary,
        },
    }
    return response


def load_runtime_config(staged: StagedSession) -> dict:
    config = sanitize_nested_strings(json.loads(staged.config_path.read_text(encoding="utf-8")))
    config["tinyfish_api_key"] = resolve_tinyfish_api_key()
    return config


def load_companies(staged: StagedSession) -> list[dict]:
    payload = json.loads(staged.companies_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("companies.json is not a list.")
    return [item for item in payload if isinstance(item, dict)]
