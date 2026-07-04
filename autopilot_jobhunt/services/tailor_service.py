from __future__ import annotations

from pathlib import Path

from ..domain.models import StagedSession
from ..storage.scan_state import LAST_SCAN_FILE_NAME, latest_output_subdir, read_last_scan
from ..tailoring.drafter import draft_application


def resolve_selected_job(job_ref: str, staged: StagedSession) -> dict | None:
    if job_ref.startswith("http"):
        for job in read_last_scan(staged.state_dir):
            if job.get("url") == job_ref:
                return job
        return {"url": job_ref}
    jobs = read_last_scan(staged.state_dir)
    digits = "".join(ch for ch in job_ref if ch.isdigit())
    if not digits:
        return None
    index = int(digits) - 1
    if 0 <= index < len(jobs):
        return jobs[index]
    return None


def selected_job_payload(job_ref: str, job: dict | None) -> dict | None:
    if job is None:
        return None
    return {
        "job_ref": job_ref,
        "score": job.get("score"),
        "title": job.get("extracted_title") or job.get("title"),
        "company": job.get("company"),
        "location": job.get("location_remote") or job.get("location"),
        "url": job.get("url"),
    }


def run_tailoring_for_session(staged: StagedSession, job_ref: str, runtime_config: dict, guidance: dict[str, str]) -> Path:
    draft_application(
        runtime_config,
        job_ref,
        last_scan_path=staged.state_dir / LAST_SCAN_FILE_NAME,
        output_dir=staged.output_dir,
        tailoring_guidance=guidance,
    )
    output_dir = latest_output_subdir(staged.output_dir)
    if not output_dir:
        raise RuntimeError("Drafting finished without creating an output directory.")
    return Path(output_dir)
