from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from google.adk.tools import ToolContext
except Exception:  # pragma: no cover - allows unit tests without ADK installed
    ToolContext = Any  # type: ignore[misc, assignment]

from job_hunt.config_utils import sanitize_nested_strings
from job_hunt.drafter import draft_application
from job_hunt.main import export_jobs
from job_hunt.scanner import (
    JOB_HISTORY_FILE,
    LAST_SCAN_FILE,
    SCAN_STATUS_FILE,
    TinyFish,
    _persist_scan_artifacts,
    discover_job_urls,
    fetch_job_details,
    filter_jobs_by_country,
    load_state,
    save_state,
    score_jobs,
)

from ..services.pdf_utils import (
    artifact_inline_bytes,
    extract_text_from_pdf_bytes,
    save_file_artifact,
)
from ..services.session_files import (
    JobSearchConfiguration,
    StagedSession,
    resolve_tinyfish_api_key,
    stage_session_files,
)
from ..services.session_runtime import (
    get_or_create_session_id,
    load_config_change_summary,
    load_internal_session_configuration,
    load_rescan_required,
    load_session_configuration,
    persist_session_configuration,
    update_rescan_state,
)
from ..services.tailoring_skill import (
    load_tailoring_guidance,
    write_tailoring_skill_manifest,
)


RAW_JOBS_FILE_NAME = "raw_jobs.json"


@contextmanager
def _session_cwd(session_dir: Path):
    old_cwd = Path.cwd()
    os.chdir(session_dir)
    try:
        yield
    finally:
        os.chdir(old_cwd)


def _load_staged_session(tool_context: Any | None) -> StagedSession:
    configuration = load_session_configuration(tool_context)
    if not configuration:
        raise RuntimeError(
            "This session is not configured yet. Use configure_candidate_search first."
        )

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


def _public_session_payload(staged: StagedSession) -> dict:
    return {
        "session_id": staged.session_id,
        "session_dir": str(staged.session_dir),
        "config_path": str(staged.config_path),
        "companies_path": str(staged.companies_path),
        "resume_path": str(staged.resume_path),
        "output_dir": str(staged.output_dir),
    }


def _latest_csv(output_dir: Path) -> str | None:
    candidates = sorted(output_dir.glob("jobs_*.csv"), key=lambda path: path.stat().st_mtime)
    if not candidates:
        return None
    return str(candidates[-1])


def _latest_pdf(output_dir: Path) -> str | None:
    candidates = sorted(output_dir.glob("jobs_*.pdf"), key=lambda path: path.stat().st_mtime)
    if not candidates:
        return None
    return str(candidates[-1])


def _latest_output_subdir(output_dir: Path) -> str | None:
    candidates = sorted(
        [path for path in output_dir.iterdir() if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
    ) if output_dir.exists() else []
    if not candidates:
        return None
    return str(candidates[-1])


def _raw_jobs_path(staged: StagedSession) -> Path:
    return staged.state_dir / RAW_JOBS_FILE_NAME


def _artifact_name_priority(name: str) -> tuple[int, int]:
    lowered = name.lower()
    score = 0
    if lowered.endswith(".pdf"):
        score += 10
    if "resume" in lowered or lowered.endswith("cv.pdf") or "_cv" in lowered:
        score += 10
    if "cover_letter" in lowered or "jobs_" in lowered or "application" in lowered:
        score -= 8
    return (score, -len(name))


def _read_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _read_last_scan(state_dir: Path) -> list[dict]:
    return _read_json_list(state_dir / "last_scan.json")


def _read_raw_jobs(state_dir: Path) -> list[dict]:
    return _read_json_list(state_dir / RAW_JOBS_FILE_NAME)


def _read_scan_status(state_dir: Path) -> dict | None:
    status_path = state_dir / SCAN_STATUS_FILE.name
    if not status_path.exists():
        return None
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload
    return None


def _write_scan_status(state_dir: Path, payload: dict[str, Any]) -> Path:
    status_path = state_dir / SCAN_STATUS_FILE.name
    status_path.parent.mkdir(parents=True, exist_ok=True)
    payload_to_write = payload.copy()
    payload_to_write["last_updated"] = datetime.now(timezone.utc).isoformat()
    status_path.write_text(json.dumps(payload_to_write, indent=2), encoding="utf-8")
    return status_path


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _top_matches(jobs: list[dict], min_score: int, top_n: int) -> list[dict]:
    indexed_matches = [
        (index, job)
        for index, job in enumerate(jobs, start=1)
        if (job.get("score") or 0) >= min_score
    ]
    ranked = sorted(
        indexed_matches,
        key=lambda item: item[1].get("score", 0),
        reverse=True,
    )
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


def _scan_input_payload(config: dict) -> dict:
    return {
        "resume_text": str(config.get("resume_text") or "").strip(),
        "company_urls": list(config.get("company_urls") or []),
        "job_urls": list(config.get("job_urls") or []),
        "target_roles": list(config.get("target_roles") or []),
        "target_locations": list(config.get("target_locations") or []),
        "llm_provider_override": config.get("llm_provider_override"),
    }


def _classify_configuration_change(previous: dict | None, current: JobSearchConfiguration) -> tuple[bool, str]:
    current_payload = asdict(current)
    if not previous:
        return True, "Saved a new configuration. Run scouting and evaluation."

    previous_input = _scan_input_payload(previous)
    current_input = _scan_input_payload(current_payload)
    if previous_input != current_input:
        return True, "Updated scan inputs. Run scouting again before evaluation."

    previous_min_score = int(previous.get("min_score") or current.min_score)
    previous_top_n = int(previous.get("top_n") or current.top_n)
    if previous_min_score != current.min_score or previous_top_n != current.top_n:
        return False, "Updated threshold or ranking settings. Reuse discovered jobs and rerank the results."

    return False, "Configuration is unchanged. Reuse the latest discovered and scored jobs."


def _has_cached_scan(staged: StagedSession) -> bool:
    return (staged.state_dir / LAST_SCAN_FILE.name).exists()


def _has_raw_jobs(staged: StagedSession) -> bool:
    return _raw_jobs_path(staged).exists()


def _build_scan_summary(staged: StagedSession, configuration: dict, jobs: list[dict]) -> dict:
    min_score = int(configuration["min_score"])
    top_n = int(configuration["top_n"])
    return {
        "total_jobs": len(jobs),
        "scored_jobs": len([job for job in jobs if job.get("score") is not None]),
        "min_score": min_score,
        "top_n": top_n,
        "above_threshold_jobs": len([job for job in jobs if (job.get("score") or 0) >= min_score]),
        "top_matches": _top_matches(jobs, min_score=min_score, top_n=top_n),
        "last_scan_path": str(staged.state_dir / LAST_SCAN_FILE.name),
    }


def _score_selection_prompt(summary: dict[str, Any]) -> str:
    top_matches = list(summary.get("top_matches") or [])
    if not top_matches:
        return (
            f"No jobs met min_score {summary['min_score']}. "
            "Lower min_score and run scoring again if you want broader matches."
        )

    example_ref = top_matches[0]["job_ref"]
    return (
        "Reply with the job_ref of the role you want to tailor, "
        f"for example {example_ref}, and I will generate a tailored resume and cover letter."
    )


def _score_result_message(summary: dict[str, Any]) -> str:
    matched_jobs = int(summary["above_threshold_jobs"])
    total_jobs = int(summary["scored_jobs"])
    min_score = int(summary["min_score"])
    if min_score <= 0:
        shown_matches = len(summary["top_matches"])
        return (
            f"Scoring complete. {total_jobs} job(s) were scored and ranked. "
            f"Showing {shown_matches} matched job(s). {_score_selection_prompt(summary)}"
        )
    if not matched_jobs:
        return (
            f"Scoring complete. {total_jobs} jobs were scored and 0 met min_score {min_score}. "
            "Lower min_score and rerun scoring if you want more matches."
        )

    shown_matches = len(summary["top_matches"])
    return (
        f"Scoring complete. {total_jobs} jobs were scored and {matched_jobs} met min_score {min_score}. "
        f"Showing the top {shown_matches} matched job(s). {_score_selection_prompt(summary)}"
    )


def _selected_job_payload(job_ref: str, job: dict[str, Any] | None) -> dict[str, Any] | None:
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


def _build_scored_jobs_response(
    staged: StagedSession,
    configuration: dict,
    jobs: list[dict],
    *,
    status_message: str,
    used_cached_results: bool,
) -> dict:
    summary = _build_scan_summary(staged, configuration, jobs)
    top_matches = list(summary["top_matches"])
    return {
        "status": "success",
        "message": _score_result_message(summary),
        "status_message": status_message,
        "used_cached_results": used_cached_results,
        "session": _public_session_payload(staged),
        "scan_summary": summary,
        "matched_job_refs": [match["job_ref"] for match in top_matches],
        "selection_prompt": _score_selection_prompt(summary),
        "next_step": (
            "tailor_application_materials"
            if summary["above_threshold_jobs"] > 0
            else "configure_candidate_search"
        ),
    }


def _build_scout_summary(
    staged: StagedSession,
    raw_jobs: list[dict],
    companies_total: int,
    direct_job_urls_total: int = 0,
) -> dict:
    return {
        "companies_total": companies_total,
        "direct_job_urls_total": direct_job_urls_total,
        "raw_jobs_count": len(raw_jobs),
        "raw_jobs_path": str(_raw_jobs_path(staged)),
        "sample_urls": [job.get("url") for job in raw_jobs[:3] if job.get("url")],
    }


def _direct_job_urls(runtime_config: dict) -> list[str]:
    adk_session = runtime_config.get("adk_session") or {}
    return [str(url).strip() for url in adk_session.get("job_urls", []) if str(url).strip()]


def _is_direct_job_only_input(*, company_urls: list[str], job_urls: list[str]) -> bool:
    return bool(job_urls) and not bool(company_urls)


def _default_location_text(runtime_config: dict) -> str:
    candidate = runtime_config.get("candidate") or {}
    target_locations = candidate.get("target_locations") or candidate.get("countries") or []
    if isinstance(target_locations, str):
        target_locations = [target_locations]
    cleaned = [str(value).strip() for value in target_locations if str(value).strip()]
    return ", ".join(cleaned)


def _direct_job_company_name(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return "Direct Job"
    return host.split(".")[0].replace("-", " ").title()


def _direct_job_title(url: str) -> str:
    path = [segment for segment in urlparse(url).path.split("/") if segment]
    if not path:
        return url
    return path[-1].replace("-", " ").replace("_", " ").title()


def _seed_direct_jobs(job_urls: list[str], runtime_config: dict) -> list[dict[str, Any]]:
    location = _default_location_text(runtime_config)
    return [
        {
            "url": url,
            "title": _direct_job_title(url),
            "snippet": "",
            "company": _direct_job_company_name(url),
            "location": location,
            "region": "Global",
            "source": "direct_job_url",
        }
        for url in job_urls
    ]


def _extend_unique_jobs(existing_jobs: list[dict], new_jobs: list[dict]) -> list[dict]:
    seen_urls = {str(job.get("url") or "").strip() for job in existing_jobs if job.get("url")}
    added_jobs: list[dict] = []
    for job in new_jobs:
        job_url = str(job.get("url") or "").strip()
        if job_url and job_url in seen_urls:
            continue
        if job_url:
            seen_urls.add(job_url)
        existing_jobs.append(job)
        added_jobs.append(job)
    return added_jobs


def _load_runtime_config(staged: StagedSession) -> dict:
    config = sanitize_nested_strings(json.loads(staged.config_path.read_text(encoding="utf-8")))
    config["tinyfish_api_key"] = resolve_tinyfish_api_key()
    return config


def _load_companies(staged: StagedSession) -> list[dict]:
    payload = json.loads(staged.companies_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("companies.json is not a list.")
    return [item for item in payload if isinstance(item, dict)]


def _merge_job_history(scored_jobs: list[dict]) -> list[dict]:
    history_by_url = {
        job["url"]: job for job in _read_json_list(Path(JOB_HISTORY_FILE.name))
        if job.get("url")
    }
    for job in scored_jobs:
        if job.get("url"):
            history_by_url[job["url"]] = job
    return list(history_by_url.values())


def _resolve_selected_job(job_ref: str, staged: StagedSession) -> dict[str, Any] | None:
    if job_ref.startswith("http"):
        for job in _read_last_scan(staged.state_dir):
            if job.get("url") == job_ref:
                return job
        return {"url": job_ref}

    jobs = _read_last_scan(staged.state_dir)
    digits = "".join(ch for ch in job_ref if ch.isdigit())
    if not digits:
        return None
    index = int(digits) - 1
    if 0 <= index < len(jobs):
        return jobs[index]
    return None


def _run_scout_for_session(staged: StagedSession, runtime_config: dict) -> tuple[list[dict], dict[str, Any]]:
    companies = _load_companies(staged)
    direct_job_urls = _direct_job_urls(runtime_config)
    discovered_jobs: list[dict] = []
    status_payload = {
        "status": "running",
        "phase": "discovering",
        "message": "Discovering jobs from configured company sources.",
        "companies_total": len(companies),
        "direct_job_urls_total": len(direct_job_urls),
        "companies_scanned": 0,
        "jobs_discovered_total": 0,
        "current_job_index": 0,
        "current_job_title": None,
        "errors": [],
    }

    with _session_cwd(staged.session_dir):
        _write_scan_status(staged.state_dir, status_payload)
        tf = TinyFish(api_key=runtime_config["tinyfish_api_key"])
        state = load_state()
        seen_urls: set[str] = set(state.get("seen_urls", []))

        if direct_job_urls:
            status_payload.update(
                {
                    "phase": "fetching_direct_jobs",
                    "message": f"Fetching {len(direct_job_urls)} direct job URL(s).",
                }
            )
            _write_scan_status(staged.state_dir, status_payload)
            direct_jobs = fetch_job_details(tf, _seed_direct_jobs(direct_job_urls, runtime_config))
            filtered_direct_jobs = filter_jobs_by_country(direct_jobs, runtime_config)
            _extend_unique_jobs(discovered_jobs, filtered_direct_jobs)
            status_payload.update(
                {
                    "jobs_discovered_total": len(discovered_jobs),
                    "message": f"Prepared {len(discovered_jobs)} direct job(s) for evaluation.",
                }
            )
            _write_scan_status(staged.state_dir, status_payload)

        for index, company in enumerate(companies, 1):
            status_payload.update(
                {
                    "phase": "discovering",
                    "company_index": index,
                    "company_name": company.get("name"),
                    "companies_scanned": index - 1,
                    "message": f"Discovering jobs for {company.get('name', 'company')} ({index}/{len(companies)})",
                }
            )
            _write_scan_status(staged.state_dir, status_payload)
            new_jobs = discover_job_urls(tf, company, seen_urls)
            if not new_jobs:
                status_payload["companies_scanned"] = index
                continue

            new_jobs = fetch_job_details(tf, new_jobs)
            seen_urls.update(job["url"] for job in new_jobs if job.get("url"))
            filtered_jobs = filter_jobs_by_country(new_jobs, runtime_config)
            _extend_unique_jobs(discovered_jobs, filtered_jobs)
            status_payload.update(
                {
                    "companies_scanned": index,
                    "jobs_discovered_total": len(discovered_jobs),
                    "message": f"Discovered {len(discovered_jobs)} jobs across {index} companies.",
                }
            )
            _write_scan_status(staged.state_dir, status_payload)

        state["seen_urls"] = list(seen_urls)
        state["last_scan"] = datetime.now(timezone.utc).isoformat()
        save_state(state)

    _write_json(_raw_jobs_path(staged), discovered_jobs)
    completed_status = {
        "status": "completed",
        "phase": "discovered",
        "message": f"Scouting complete. {len(discovered_jobs)} jobs are ready for evaluation.",
        "companies_total": len(companies),
        "direct_job_urls_total": len(direct_job_urls),
        "companies_scanned": len(companies),
        "jobs_discovered_total": len(discovered_jobs),
        "raw_jobs_path": str(_raw_jobs_path(staged)),
    }
    _write_scan_status(staged.state_dir, completed_status)
    return discovered_jobs, completed_status


def _run_evaluator_for_session(staged: StagedSession, runtime_config: dict) -> tuple[list[dict], dict[str, Any]]:
    raw_jobs = _read_raw_jobs(staged.state_dir)
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
    _write_scan_status(staged.state_dir, status_payload)

    scored_job_urls: set[str] = set()

    def _write_running_status(**updates: Any) -> None:
        status_payload.update(updates)
        _write_scan_status(staged.state_dir, status_payload)

    def _on_job_started(job_index: int, job: dict[str, Any], total_jobs: int) -> None:
        _write_running_status(
            message=f"Scoring job {job_index}/{total_jobs}: {job.get('title')}",
            current_job_index=job_index,
            current_job_title=job.get("title"),
        )

    def _on_scored_job(job: dict[str, Any]) -> None:
        job_url = str(job.get("url") or "").strip()
        if job_url:
            scored_job_urls.add(job_url)

        _write_running_status(
            jobs_scored_total=len(scored_job_urls),
            current_job_title=job.get("extracted_title") or job.get("title"),
        )

    resume_text = staged.resume_path.read_text(encoding="utf-8")
    scored_jobs = score_jobs(
        raw_jobs,
        resume_text,
        runtime_config,
        on_job_started=_on_job_started,
        on_scored_job=_on_scored_job,
    )

    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    scored_jobs_with_date = []
    for job in scored_jobs:
        payload = job.copy()
        payload["scan_date"] = scan_date
        scored_jobs_with_date.append(payload)

    with _session_cwd(staged.session_dir):
        _persist_scan_artifacts(
            scored_jobs_with_date,
            _merge_job_history(scored_jobs_with_date),
            quiet=True,
        )

    completed_status = {
        "status": "completed",
        "phase": "completed",
        "message": f"Evaluation complete. {len(scored_jobs_with_date)} jobs scored.",
        "jobs_discovered_total": len(raw_jobs),
        "jobs_scored_total": len(scored_jobs_with_date),
        "jobs_above_threshold_total": len(
            [job for job in scored_jobs_with_date if (job.get("score") or 0) >= runtime_config["candidate"]["min_score"]]
        ),
        "last_scan_path": str(staged.state_dir / LAST_SCAN_FILE.name),
    }
    _write_scan_status(staged.state_dir, completed_status)
    return scored_jobs_with_date, completed_status


def _run_tailoring_for_session(
    staged: StagedSession,
    job_ref: str,
    runtime_config: dict,
    guidance: dict[str, str],
) -> Path:
    with _session_cwd(staged.session_dir):
        draft_application(runtime_config, job_ref, tailoring_guidance=guidance)
    output_dir = _latest_output_subdir(staged.output_dir)
    if not output_dir:
        raise RuntimeError("Drafting finished without creating an output directory.")
    return Path(output_dir)


def _run_export_for_session(
    staged: StagedSession,
    min_score: int,
    days: int,
    export_format: str,
) -> dict[str, str | None]:
    with _session_cwd(staged.session_dir):
        return export_jobs(min_score=min_score, days=days, export_format=export_format)


def _cached_scan_response(
    staged: StagedSession,
    configuration: dict,
    *,
    message: str,
) -> dict:
    jobs = _read_last_scan(staged.state_dir)
    return _build_scored_jobs_response(
        staged,
        configuration,
        jobs,
        status_message=message,
        used_cached_results=True,
    )


async def _resolve_resume_pdf_artifact(
    tool_context: ToolContext | None,
    requested_artifact_name: str | None,
) -> tuple[str, Any]:
    if tool_context is None or not hasattr(tool_context, "load_artifact"):
        raise RuntimeError(
            "Resume PDF support requires the ADK artifact service. Paste resume text instead."
        )

    if requested_artifact_name:
        artifact = await tool_context.load_artifact(requested_artifact_name)
        if artifact is None:
            raise RuntimeError(
                f"Resume PDF artifact '{requested_artifact_name}' was not found in this session."
            )
        return requested_artifact_name, artifact

    artifact_names = await tool_context.list_artifacts()
    pdf_candidates = [name for name in artifact_names if str(name).lower().endswith(".pdf")]
    if not pdf_candidates:
        raise RuntimeError(
            "No uploaded resume PDF was found. Paste resume text or upload a resume PDF first."
        )

    ranked_candidates = sorted(
        pdf_candidates,
        key=lambda name: _artifact_name_priority(name),
        reverse=True,
    )
    top_candidate = ranked_candidates[0]
    if len(ranked_candidates) > 1:
        best_score = _artifact_name_priority(top_candidate)
        second_score = _artifact_name_priority(ranked_candidates[1])
        if best_score == second_score and "resume" not in top_candidate.lower() and "cv" not in top_candidate.lower():
            raise RuntimeError(
                "Multiple PDF artifacts are attached to this session. Pass resume_pdf_artifact with the uploaded resume filename."
            )

    artifact = await tool_context.load_artifact(top_candidate)
    if artifact is None:
        raise RuntimeError(f"Resume PDF artifact '{top_candidate}' could not be loaded.")
    return top_candidate, artifact


async def _resolve_resume_text_input(
    *,
    resume_text: str,
    resume_pdf_artifact: str | None,
    tool_context: ToolContext | None,
) -> tuple[str, dict[str, Any]]:
    cleaned_text = str(resume_text or "").strip()
    if not cleaned_text or resume_pdf_artifact:
        artifact_name, artifact = await _resolve_resume_pdf_artifact(tool_context, resume_pdf_artifact)
        extracted_text = extract_text_from_pdf_bytes(artifact_inline_bytes(artifact))
        return extracted_text, {
            "type": "pdf_artifact",
            "artifact_name": artifact_name,
            "resume_chars": len(extracted_text),
        }

    return cleaned_text, {
        "type": "text",
        "artifact_name": None,
        "resume_chars": len(cleaned_text),
    }


def _find_first_matching_file(output_dir: Path, pattern: str) -> str | None:
    matches = sorted(output_dir.glob(pattern))
    if not matches:
        return None
    return str(matches[0])


async def _attach_downloadable_artifacts(
    tool_context: ToolContext | None,
    *paths: Path,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        saved_artifact = await save_file_artifact(
            tool_context,
            path,
            artifact_name=path.name,
            custom_metadata={"source_path": str(path)},
        )
        if saved_artifact:
            artifacts.append(saved_artifact)
    return artifacts


async def configure_candidate_search(
    resume_text: str = "",
    company_urls: list[str] | None = None,
    job_urls: list[str] | None = None,
    target_roles: list[str] | None = None,
    target_locations: list[str] | None = None,
    min_score: int = 60,
    top_n: int = 5,
    llm_provider_override: str | None = None,
    resume_pdf_artifact: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict:
    """
    Validate and persist the current candidate + search inputs for this ADK session.

    Accept either pasted resume text or a session-uploaded resume PDF artifact.
    """
    session_id = get_or_create_session_id(tool_context)
    previous_internal = load_internal_session_configuration(tool_context)
    try:
        resolved_resume_text, resume_source = await _resolve_resume_text_input(
            resume_text=resume_text,
            resume_pdf_artifact=resume_pdf_artifact,
            tool_context=tool_context,
        )
    except Exception as exc:
        return {"status": "error", "message": f"Configuration failed: {exc}"}
    direct_job_only_input = _is_direct_job_only_input(
        company_urls=list(company_urls or []),
        job_urls=list(job_urls or []),
    )
    effective_min_score = 0 if direct_job_only_input and min_score == 60 else min_score
    effective_top_n = len(list(job_urls or [])) if direct_job_only_input and top_n == 5 and job_urls else top_n
    config = JobSearchConfiguration(
        resume_text=resolved_resume_text,
        company_urls=list(company_urls or []),
        job_urls=list(job_urls or []),
        target_roles=list(target_roles or []),
        target_locations=list(target_locations or []),
        min_score=effective_min_score,
        top_n=effective_top_n,
        llm_provider_override=llm_provider_override,
    ).validated()

    staged = stage_session_files(session_id, config)
    scan_input_changed, config_change_summary = _classify_configuration_change(previous_internal, config)
    cached_scan_exists = _has_cached_scan(staged)
    rescan_required = scan_input_changed or not _has_raw_jobs(staged)
    if not _has_raw_jobs(staged) and not scan_input_changed:
        config_change_summary = (
            "Updated threshold or ranking settings, but no discovered jobs are cached yet. "
            "Run scouting before evaluation."
        )

    persist_session_configuration(
        tool_context,
        config,
        staged,
        rescan_required=rescan_required,
        config_change_summary=config_change_summary,
    )

    response = {
        "status": "success",
        "message": (
            "Direct job URLs saved. Fetch and score them next."
            if direct_job_only_input and rescan_required
            else "Candidate search configuration saved. Run scouting next."
            if rescan_required
            else "Candidate search configuration updated. Cached jobs can be reused."
        ),
        "configuration": config.public_summary() | {"resume_source": resume_source},
        "session": _public_session_payload(staged),
        "next_step": "scan_company_jobs" if rescan_required else "score_and_rank_jobs",
        "scan_reuse": {
            "rescan_required": rescan_required,
            "cached_discovered_jobs_available": _has_raw_jobs(staged),
            "cached_scored_results_available": cached_scan_exists,
            "reason": config_change_summary,
        },
    }

    if cached_scan_exists and not scan_input_changed:
        response["scan_summary"] = _build_scan_summary(
            staged,
            config.public_summary(),
            _read_last_scan(staged.state_dir),
        )

    return response


def scan_company_jobs(tool_context: ToolContext | None = None) -> dict:
    """
    Discover jobs from configured company sources and stage them for evaluation.
    """
    configuration = load_session_configuration(tool_context)
    if not configuration:
        return {
            "status": "error",
            "message": "This session is not configured yet. Use configure_candidate_search first.",
        }

    staged = _load_staged_session(tool_context)
    if not load_rescan_required(tool_context) and _has_raw_jobs(staged):
        raw_jobs = _read_raw_jobs(staged.state_dir)
        scout_summary = _build_scout_summary(
            staged,
            raw_jobs,
            companies_total=len(json.loads(staged.companies_path.read_text(encoding="utf-8"))),
            direct_job_urls_total=len(configuration.get("job_urls") or []),
        )
        return {
            "status": "success",
            "message": "Using cached discovered jobs. No fresh scouting was needed.",
            "used_cached_results": True,
            "session": _public_session_payload(staged),
            "scout_summary": scout_summary,
            "next_step": "score_and_rank_jobs",
        }

    try:
        raw_jobs, status = _run_scout_for_session(staged, _load_runtime_config(staged))
    except Exception as exc:
        return {"status": "error", "message": f"Scouting failed: {exc}"}

    return {
        "status": "success",
        "message": status["message"],
        "used_cached_results": False,
        "session": _public_session_payload(staged),
        "scout_summary": _build_scout_summary(
            staged,
            raw_jobs,
            companies_total=status["companies_total"],
            direct_job_urls_total=status.get("direct_job_urls_total", 0),
        ),
        "next_step": "score_and_rank_jobs",
    }


def score_and_rank_jobs(tool_context: ToolContext | None = None) -> dict:
    """
    Score discovered jobs against the candidate profile and return the ranked matches.
    """
    configuration = load_session_configuration(tool_context)
    if not configuration:
        return {
            "status": "error",
            "message": "This session is not configured yet. Use configure_candidate_search first.",
        }

    staged = _load_staged_session(tool_context)
    if not load_rescan_required(tool_context) and _has_cached_scan(staged):
        reuse_reason = load_config_change_summary(tool_context) or "Using cached scored jobs from the last completed evaluation."
        return _cached_scan_response(
            staged,
            configuration,
            message=f"{reuse_reason} No re-evaluation was needed.",
        )

    try:
        scored_jobs, status = _run_evaluator_for_session(staged, _load_runtime_config(staged))
    except Exception as exc:
        return {"status": "error", "message": f"Evaluation failed: {exc}"}

    update_rescan_state(
        tool_context,
        rescan_required=False,
        config_change_summary="Using cached scored jobs from the last completed evaluation.",
    )

    return _build_scored_jobs_response(
        staged,
        configuration,
        scored_jobs,
        status_message=status["message"],
        used_cached_results=False,
    )


async def tailor_application_materials(job_ref: str, tool_context: ToolContext | None = None) -> dict:
    """
    Use the repo-local tailoring skill guidance to draft resume and cover-letter materials.
    """
    try:
        staged = _load_staged_session(tool_context)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc)}

    guidance = load_tailoring_guidance()
    try:
        output_dir = _run_tailoring_for_session(
            staged,
            job_ref,
            _load_runtime_config(staged),
            guidance,
        )
    except Exception as exc:
        return {"status": "error", "message": f"Tailoring failed: {exc}"}

    selected_job = _resolve_selected_job(job_ref, staged)
    manifest_path = write_tailoring_skill_manifest(
        output_dir,
        staged=staged,
        job_ref=job_ref,
        guidance=guidance,
        selected_job=selected_job,
    )
    resume_md_path = _find_first_matching_file(output_dir, "resume_*.md")
    resume_pdf_path = _find_first_matching_file(output_dir, "resume_*.pdf")
    cover_md_path = _find_first_matching_file(output_dir, "cover_letter_*.md")
    cover_pdf_path = _find_first_matching_file(output_dir, "cover_letter_*.pdf")
    downloadable_artifacts = await _attach_downloadable_artifacts(
        tool_context,
        *(Path(path) for path in [resume_pdf_path, cover_pdf_path] if path),
    )

    return {
        "status": "success",
        "message": "Tailored application materials generated. Downloadable PDF attachments are ready in the ADK UI.",
        "session": _public_session_payload(staged),
        "selected_job": _selected_job_payload(job_ref, selected_job),
        "draft_output_dir": str(output_dir),
        "files": {
            "resume_markdown_path": resume_md_path,
            "resume_pdf_path": resume_pdf_path,
            "cover_letter_markdown_path": cover_md_path,
            "cover_letter_pdf_path": cover_pdf_path,
            "application_info_path": str(output_dir / "application_info.txt"),
            "tailoring_skill_manifest_path": str(manifest_path),
        },
        "downloadable_artifacts": downloadable_artifacts,
        "download_instructions": "Use the attached PDF download chip/button in the ADK UI instead of any storage URI.",
        "skill": {
            "name": guidance["skill_name"],
            "path": guidance["skill_path"],
            "manifest_path": str(manifest_path),
        },
    }


async def export_results(
    min_score: int = 0,
    days: int = 0,
    export_format: str = "pdf",
    tool_context: ToolContext | None = None,
) -> dict:
    """
    Export the current session's scored results to PDF, CSV, or both.
    """
    try:
        staged = _load_staged_session(tool_context)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc)}

    try:
        export_paths = _run_export_for_session(
            staged,
            min_score=min_score,
            days=days,
            export_format=export_format,
        )
    except SystemExit as exc:
        return {"status": "error", "message": str(exc)}
    except Exception as exc:
        return {"status": "error", "message": f"Export failed: {exc}"}

    downloadable_artifacts = await _attach_downloadable_artifacts(
        tool_context,
        *(Path(path) for path in export_paths.values() if path),
    )

    return {
        "status": "success",
        "message": "Export complete. Downloadable file attachments are ready in the ADK UI.",
        "session": _public_session_payload(staged),
        "export_format": export_format,
        "csv_path": export_paths.get("csv_path") or _latest_csv(staged.output_dir),
        "pdf_path": export_paths.get("pdf_path") or _latest_pdf(staged.output_dir),
        "downloadable_artifacts": downloadable_artifacts,
        "download_instructions": "Use the attached download chip/button in the ADK UI instead of any storage URI.",
    }


def show_current_configuration(tool_context: ToolContext | None = None) -> dict:
    """
    Show the current session's saved job-search configuration.
    """
    configuration = load_session_configuration(tool_context)
    if not configuration:
        return {
            "status": "error",
            "message": "This session is not configured yet.",
        }

    staged = _load_staged_session(tool_context)
    return {
        "status": "success",
        "message": "Current session configuration loaded.",
        "configuration": configuration,
        "rescan_required": load_rescan_required(tool_context),
        "configuration_change_summary": load_config_change_summary(tool_context),
        "raw_jobs_available": _has_raw_jobs(staged),
        "scored_results_available": _has_cached_scan(staged),
        "session": _public_session_payload(staged),
    }


def show_scan_status(tool_context: ToolContext | None = None) -> dict:
    """
    Show the latest scout/evaluator progress for the current session.
    """
    try:
        staged = _load_staged_session(tool_context)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc)}

    configuration = load_session_configuration(tool_context) or {}
    scan_status = _read_scan_status(staged.state_dir)
    if scan_status:
        return {
            "status": "success",
            "message": str(scan_status.get("message") or "Scan status loaded."),
            "session": _public_session_payload(staged),
            "scan_status": scan_status,
        }

    if _has_cached_scan(staged) and configuration:
        jobs = _read_last_scan(staged.state_dir)
        summary = _build_scan_summary(staged, configuration, jobs)
        return {
            "status": "success",
            "message": "No active scout or evaluator run is in progress. Returning the last completed evaluation summary.",
            "session": _public_session_payload(staged),
            "scan_status": {
                "status": "completed",
                "phase": "completed",
                "message": "Last completed evaluation results are available.",
                "jobs_scored_total": summary["scored_jobs"],
                "jobs_above_threshold_total": summary["above_threshold_jobs"],
                "top_matches_count": len(summary["top_matches"]),
                "last_scan_path": summary["last_scan_path"],
            },
        }

    if _has_raw_jobs(staged):
        raw_jobs = _read_raw_jobs(staged.state_dir)
        return {
            "status": "success",
            "message": "Discovered jobs are ready for evaluation.",
            "session": _public_session_payload(staged),
            "scan_status": {
                "status": "completed",
                "phase": "discovered",
                "message": "Scouting is complete and jobs are waiting for evaluation.",
                "jobs_discovered_total": len(raw_jobs),
                "raw_jobs_path": str(_raw_jobs_path(staged)),
            },
        }

    return {
        "status": "error",
        "message": "No scout or evaluator status is available yet. Run scouting first.",
        "session": _public_session_payload(staged),
    }


async def configure_job_search(*args, **kwargs) -> dict:
    """
    Backward-compatible alias for the old single-agent configuration tool name.
    """
    return await configure_candidate_search(*args, **kwargs)


def scan_configured_jobs(tool_context: ToolContext | None = None) -> dict:
    """
    Backward-compatible combined flow: scout first, then evaluate.
    """
    scout_result = scan_company_jobs(tool_context=tool_context)
    if scout_result.get("status") != "success":
        return scout_result
    return score_and_rank_jobs(tool_context=tool_context)


async def draft_for_job(job_ref: str, tool_context: ToolContext | None = None) -> dict:
    """
    Backward-compatible alias for the old tailoring tool name.
    """
    return await tailor_application_materials(job_ref=job_ref, tool_context=tool_context)
