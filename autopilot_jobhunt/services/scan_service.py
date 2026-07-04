from __future__ import annotations

import json
from datetime import datetime, timezone

from ..discovery import TinyFish, discover_job_urls, fetch_job_details, filter_jobs_by_country
from ..domain.models import StagedSession
from ..storage.scan_state import RAW_JOBS_FILE_NAME, read_json_dict, write_json, write_scan_status
from .config_service import load_companies


SEEN_JOBS_FILE_NAME = "seen_jobs.json"


def _seen_jobs_path(staged: StagedSession):
    return staged.state_dir / SEEN_JOBS_FILE_NAME


def _load_seen_state(staged: StagedSession) -> dict:
    return read_json_dict(_seen_jobs_path(staged)) or {"seen_urls": []}


def _save_seen_state(staged: StagedSession, state: dict) -> None:
    write_json(_seen_jobs_path(staged), state)


def build_scout_summary(staged: StagedSession, raw_jobs: list[dict], companies_total: int) -> dict:
    return {
        "companies_total": companies_total,
        "raw_jobs_count": len(raw_jobs),
        "raw_jobs_path": str(staged.state_dir / RAW_JOBS_FILE_NAME),
        "sample_urls": [job.get("url") for job in raw_jobs[:3] if job.get("url")],
    }


def run_scout_for_session(staged: StagedSession, runtime_config: dict) -> tuple[list[dict], dict]:
    companies = load_companies(staged)
    discovered_jobs: list[dict] = []
    status_payload = {
        "status": "running",
        "phase": "discovering",
        "message": "Discovering jobs from configured company sources.",
        "companies_total": len(companies),
        "companies_scanned": 0,
        "jobs_discovered_total": 0,
        "current_job_index": 0,
        "current_job_title": None,
        "errors": [],
    }
    write_scan_status(staged.state_dir, status_payload)
    tf = TinyFish(api_key=runtime_config["tinyfish_api_key"])
    state = _load_seen_state(staged)
    seen_urls: set[str] = set(state.get("seen_urls", []))
    for index, company in enumerate(companies, start=1):
        status_payload.update(
            {
                "company_index": index,
                "company_name": company.get("name"),
                "companies_scanned": index - 1,
                "message": f"Discovering jobs for {company.get('name', 'company')} ({index}/{len(companies)})",
            }
        )
        write_scan_status(staged.state_dir, status_payload)
        new_jobs = discover_job_urls(tf, company, seen_urls)
        if not new_jobs:
            status_payload["companies_scanned"] = index
            continue
        new_jobs = fetch_job_details(tf, new_jobs)
        seen_urls.update(job["url"] for job in new_jobs if job.get("url"))
        filtered_jobs = filter_jobs_by_country(new_jobs, runtime_config)
        discovered_jobs.extend(filtered_jobs)
        status_payload.update(
            {
                "companies_scanned": index,
                "jobs_discovered_total": len(discovered_jobs),
                "message": f"Discovered {len(discovered_jobs)} jobs across {index} companies.",
            }
        )
        write_scan_status(staged.state_dir, status_payload)
    state["seen_urls"] = list(seen_urls)
    state["last_scan"] = datetime.now(timezone.utc).isoformat()
    _save_seen_state(staged, state)
    write_json(staged.state_dir / RAW_JOBS_FILE_NAME, discovered_jobs)
    completed_status = {
        "status": "completed",
        "phase": "discovered",
        "message": f"Scouting complete. {len(discovered_jobs)} jobs are ready for evaluation.",
        "companies_total": len(companies),
        "companies_scanned": len(companies),
        "jobs_discovered_total": len(discovered_jobs),
        "raw_jobs_path": str(staged.state_dir / RAW_JOBS_FILE_NAME),
    }
    write_scan_status(staged.state_dir, completed_status)
    return discovered_jobs, completed_status
