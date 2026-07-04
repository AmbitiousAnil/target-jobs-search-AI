from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..domain.models import StagedSession
from ..scoring import score_jobs
from ..storage.scan_state import (
    JOB_HISTORY_FILE_NAME,
    LAST_SCAN_FILE_NAME,
    RAW_JOBS_FILE_NAME,
    read_job_history,
    read_last_scan,
    read_raw_jobs,
    write_json,
    write_scan_status,
)


def top_matches(jobs: list[dict], min_score: int, top_n: int) -> list[dict]:
    indexed_matches = [(index, job) for index, job in enumerate(jobs, start=1) if (job.get("score") or 0) >= min_score]
    ranked = sorted(indexed_matches, key=lambda item: item[1].get("score", 0), reverse=True)
    return [
        {
            "rank": rank,
            "job_ref": f"#{index}",
            "score": job.get("score"),
            "title": job.get("extracted_title") or job.get("title"),
            "company": job.get("company"),
            "location": job.get("location_remote") or job.get("location"),
            "url": job.get("url"),
            "reason": job.get("reason"),
        }
        for rank, (index, job) in enumerate(ranked[:top_n], start=1)
    ]


def build_scan_summary(staged: StagedSession, configuration: dict, jobs: list[dict]) -> dict:
    min_score = int(configuration["min_score"])
    top_n = int(configuration["top_n"])
    return {
        "total_jobs": len(jobs),
        "scored_jobs": len([job for job in jobs if job.get("score") is not None]),
        "min_score": min_score,
        "top_n": top_n,
        "above_threshold_jobs": len([job for job in jobs if (job.get("score") or 0) >= min_score]),
        "top_matches": top_matches(jobs, min_score=min_score, top_n=top_n),
        "last_scan_path": str(staged.state_dir / LAST_SCAN_FILE_NAME),
    }


def _merge_job_history(staged: StagedSession, scored_jobs: list[dict]) -> list[dict]:
    history_by_url = {job["url"]: job for job in read_job_history(staged.state_dir) if job.get("url")}
    for job in scored_jobs:
        if job.get("url"):
            history_by_url[job["url"]] = job
    return list(history_by_url.values())


def run_evaluator_for_session(staged: StagedSession, runtime_config: dict) -> tuple[list[dict], dict]:
    raw_jobs = read_raw_jobs(staged.state_dir)
    if not raw_jobs:
        raise RuntimeError("No discovered jobs are available yet. Run scan_company_jobs first.")
    status_payload = {
        "status": "running",
        "phase": "scoring",
        "message": f"Scoring {len(raw_jobs)} discovered jobs.",
        "jobs_discovered_total": len(raw_jobs),
        "jobs_scored_total": 0,
        "current_job_index": 0,
        "current_job_title": None,
    }
    write_scan_status(staged.state_dir, status_payload)
    scored_job_urls: set[str] = set()

    def write_running_status(**updates: Any) -> None:
        status_payload.update(updates)
        write_scan_status(staged.state_dir, status_payload)

    def on_job_started(job_index: int, job: dict[str, Any], total_jobs: int) -> None:
        write_running_status(
            message=f"Scoring job {job_index}/{total_jobs}: {job.get('title')}",
            current_job_index=job_index,
            current_job_title=job.get("title"),
        )

    def on_scored_job(job: dict[str, Any]) -> None:
        job_url = str(job.get("url") or "").strip()
        if job_url:
            scored_job_urls.add(job_url)
        write_running_status(
            jobs_scored_total=len(scored_job_urls),
            current_job_title=job.get("extracted_title") or job.get("title"),
        )

    resume_text = staged.resume_path.read_text(encoding="utf-8")
    scored_jobs = score_jobs(raw_jobs, resume_text, runtime_config, on_job_started=on_job_started, on_scored_job=on_scored_job)
    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for job in scored_jobs:
        job["scan_date"] = scan_date
    write_json(staged.state_dir / LAST_SCAN_FILE_NAME, scored_jobs)
    write_json(staged.state_dir / JOB_HISTORY_FILE_NAME, _merge_job_history(staged, scored_jobs))
    completed_status = {
        "status": "completed",
        "phase": "completed",
        "message": f"Evaluation complete. {len(scored_jobs)} jobs scored.",
        "jobs_discovered_total": len(raw_jobs),
        "jobs_scored_total": len(scored_jobs),
        "jobs_above_threshold_total": len([job for job in scored_jobs if (job.get('score') or 0) >= runtime_config.get('candidate', {}).get('min_score', 60)]),
        "last_scan_path": str(staged.state_dir / LAST_SCAN_FILE_NAME),
    }
    write_scan_status(staged.state_dir, completed_status)
    return scored_jobs, completed_status


def read_cached_scan(staged: StagedSession) -> list[dict]:
    return read_last_scan(staged.state_dir)
