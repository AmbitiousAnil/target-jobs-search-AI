from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from google.adk.tools import ToolContext
except Exception:  # pragma: no cover
    ToolContext = Any  # type: ignore[misc, assignment]

from ..domain.models import JobSearchConfiguration, StagedSession
from ..export.artifacts import (
    apply_download_labels,
    artifact_inline_bytes,
    build_download_markdown,
    save_file_artifact,
)
from ..export.pdf import extract_text_from_pdf_bytes
from ..services.config_service import (
    configure_session,
    has_cached_scan,
    has_raw_jobs,
    load_runtime_config,
    load_staged_session,
    public_session_payload,
)
from ..services.export_service import run_export_for_session as _export_service_run
from ..services.scan_service import build_scout_summary, run_scout_for_session as _scan_service_run
from ..services.score_service import (
    build_scan_summary,
    read_cached_scan,
    run_evaluator_for_session as _score_service_run,
)
from ..services.tailor_service import (
    resolve_selected_job,
    run_tailoring_for_session as _tailor_service_run,
    selected_job_payload,
)
from ..storage.scan_state import (
    LAST_SCAN_FILE_NAME,
    RAW_JOBS_FILE_NAME,
    latest_matching_file,
    read_raw_jobs,
    read_scan_status,
)
from ..storage.session_state import (
    load_config_change_summary,
    load_rescan_required,
    load_session_configuration,
    update_rescan_state,
)
from ..tailoring.skill import load_tailoring_guidance, write_tailoring_skill_manifest
from .formatting import build_scored_jobs_response


def _run_scout_for_session(staged, runtime_config):
    return _scan_service_run(staged, runtime_config)




def _run_evaluator_for_session(staged, runtime_config):
    return _score_service_run(staged, runtime_config)


def _run_tailoring_for_session(staged, job_ref, runtime_config, guidance):
    return _tailor_service_run(staged, job_ref, runtime_config, guidance)


def _run_export_for_session(staged, min_score, days, export_format):
    return _export_service_run(staged, min_score, days, export_format)


async def _resolve_resume_pdf_artifact(tool_context: ToolContext | None, requested_artifact_name: str | None) -> tuple[str, Any]:
    if tool_context is None or not hasattr(tool_context, "load_artifact"):
        raise RuntimeError("Resume PDF support requires ADK artifact service. Paste resume text instead.")
    if requested_artifact_name:
        artifact = await tool_context.load_artifact(requested_artifact_name)
        if artifact is None:
            raise RuntimeError(f"Resume PDF artifact '{requested_artifact_name}' was not found in this session.")
        return requested_artifact_name, artifact
    artifact_names = await tool_context.list_artifacts()
    pdf_candidates = [name for name in artifact_names if str(name).lower().endswith(".pdf")]
    if not pdf_candidates:
        raise RuntimeError("No uploaded resume PDF was found. Paste resume text or upload a resume PDF first.")
    artifact_name = sorted(pdf_candidates)[0]
    artifact = await tool_context.load_artifact(artifact_name)
    if artifact is None:
        raise RuntimeError(f"Resume PDF artifact '{artifact_name}' could not be loaded.")
    return artifact_name, artifact


async def _resolve_resume_text_input(*, resume_text: str, resume_pdf_artifact: str | None, tool_context: ToolContext | None) -> tuple[str, dict[str, Any]]:
    cleaned_text = str(resume_text or "").strip()
    if cleaned_text and not resume_pdf_artifact:
        return cleaned_text, {"type": "text", "artifact_name": None, "resume_chars": len(cleaned_text)}
    artifact_name, artifact = await _resolve_resume_pdf_artifact(tool_context, resume_pdf_artifact)
    extracted_text = extract_text_from_pdf_bytes(artifact_inline_bytes(artifact))
    return extracted_text, {"type": "pdf_artifact", "artifact_name": artifact_name, "resume_chars": len(extracted_text)}


async def _attach_downloadable_artifacts(tool_context: ToolContext | None, *paths: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in paths:
        if path.exists():
            saved_artifact = await save_file_artifact(tool_context, path, artifact_name=path.name, custom_metadata={"source_path": str(path)})
            if saved_artifact:
                artifacts.append(saved_artifact)
    return artifacts


async def configure_candidate_search(
    resume_text: str = "",
    company_urls: list[str] | None = None,
    target_roles: list[str] | None = None,
    target_locations: list[str] | None = None,
    min_score: int = 60,
    top_n: int = 5,
    llm_provider_override: str | None = None,
    resume_pdf_artifact: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict:
    try:
        resolved_resume_text, resume_source = await _resolve_resume_text_input(
            resume_text=resume_text,
            resume_pdf_artifact=resume_pdf_artifact,
            tool_context=tool_context,
        )
        config = JobSearchConfiguration(
            resume_text=resolved_resume_text,
            company_urls=list(company_urls or []),
            target_roles=list(target_roles or []),
            target_locations=list(target_locations or []),
            min_score=min_score,
            top_n=top_n,
            llm_provider_override=llm_provider_override,
        )
        result = configure_session(tool_context, config)
        result["configuration"] = result["configuration"] | {"resume_source": resume_source}
        if has_cached_scan(load_staged_session(tool_context)) and not result["scan_reuse"]["rescan_required"]:
            staged = load_staged_session(tool_context)
            configuration = load_session_configuration(tool_context) or {}
            result["scan_summary"] = build_scan_summary(staged, configuration, read_cached_scan(staged))
        return result
    except Exception as exc:
        return {"status": "error", "message": f"Configuration failed: {exc}"}


def scan_company_jobs(tool_context: ToolContext | None = None) -> dict:
    configuration = load_session_configuration(tool_context)
    if not configuration:
        return {"status": "error", "message": "This session is not configured yet. Use configure_candidate_search first."}
    staged = load_staged_session(tool_context)
    if not load_rescan_required(tool_context) and has_raw_jobs(staged):
        raw_jobs = read_raw_jobs(staged.state_dir)
        return {
            "status": "success",
            "message": "Using cached discovered jobs. No fresh scouting was needed.",
            "used_cached_results": True,
            "session": public_session_payload(staged),
            "scout_summary": build_scout_summary(staged, raw_jobs, companies_total=len(configuration.get("company_urls") or [])),
            "next_step": "score_and_rank_jobs",
        }
    try:
        raw_jobs, status = _run_scout_for_session(staged, load_runtime_config(staged))
    except Exception as exc:
        return {"status": "error", "message": f"Scouting failed: {exc}"}
    return {
        "status": "success",
        "message": status["message"],
        "used_cached_results": False,
        "session": public_session_payload(staged),
        "scout_summary": build_scout_summary(staged, raw_jobs, companies_total=status["companies_total"]),
        "next_step": "score_and_rank_jobs",
    }


def score_and_rank_jobs(tool_context: ToolContext | None = None) -> dict:
    configuration = load_session_configuration(tool_context)
    if not configuration:
        return {"status": "error", "message": "This session is not configured yet. Use configure_candidate_search first."}
    staged = load_staged_session(tool_context)
    if not load_rescan_required(tool_context) and has_cached_scan(staged):
        reuse_reason = load_config_change_summary(tool_context) or "Using cached scored jobs from the last completed evaluation."
        return build_scored_jobs_response(
            staged,
            configuration,
            read_cached_scan(staged),
            status_message=f"{reuse_reason} No re-evaluation was needed.",
            used_cached_results=True,
        )
    try:
        scored_jobs, status = _run_evaluator_for_session(staged, load_runtime_config(staged))
    except Exception as exc:
        return {"status": "error", "message": f"Evaluation failed: {exc}"}
    update_rescan_state(tool_context, rescan_required=False, config_change_summary="Using cached scored jobs from the last completed evaluation.")
    return build_scored_jobs_response(
        staged,
        configuration,
        scored_jobs,
        status_message=status["message"],
        used_cached_results=False,
    )


async def tailor_application_materials(job_ref: str, tool_context: ToolContext | None = None) -> dict:
    try:
        staged = load_staged_session(tool_context)
        guidance = load_tailoring_guidance()
        output_dir = _run_tailoring_for_session(staged, job_ref, load_runtime_config(staged), guidance)
        selected_job = resolve_selected_job(job_ref, staged)
        manifest_path = write_tailoring_skill_manifest(output_dir, staged=staged, job_ref=job_ref, guidance=guidance, selected_job=selected_job)
        resume_md_path = latest_matching_file(output_dir, "resume_*.md")
        resume_pdf_path = latest_matching_file(output_dir, "resume_*.pdf")
        cover_md_path = latest_matching_file(output_dir, "cover_letter_*.md")
        cover_pdf_path = latest_matching_file(output_dir, "cover_letter_*.pdf")
        downloadable_artifacts = await _attach_downloadable_artifacts(
            tool_context,
            *(Path(path) for path in [resume_pdf_path, cover_pdf_path] if path),
        )
        downloadable_artifacts = apply_download_labels(downloadable_artifacts, {"resume_": "Tailored Resume PDF", "cover_letter_": "Tailored Cover Letter PDF"})
        return {
            "status": "success",
            "message": "Tailored application materials generated. Use clickable download links below.",
            "session": public_session_payload(staged),
            "selected_job": selected_job_payload(job_ref, selected_job),
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
            "download_markdown": build_download_markdown(downloadable_artifacts),
            "download_instructions": "Use clickable markdown links below.",
            "skill": {"name": guidance["skill_name"], "path": guidance["skill_path"], "manifest_path": str(manifest_path)},
        }
    except Exception as exc:
        return {"status": "error", "message": f"Tailoring failed: {exc}"}


async def export_results(min_score: int = 0, days: int = 0, export_format: str = "pdf", tool_context: ToolContext | None = None) -> dict:
    try:
        staged = load_staged_session(tool_context)
        export_paths = _run_export_for_session(staged, min_score=min_score, days=days, export_format=export_format)
        downloadable_artifacts = await _attach_downloadable_artifacts(tool_context, *(Path(path) for path in export_paths.values() if path))
        downloadable_artifacts = apply_download_labels(downloadable_artifacts, {".pdf": "Scored Jobs PDF Export", ".csv": "Scored Jobs CSV Export"})
        return {
            "status": "success",
            "message": "Export complete. Use clickable download links below.",
            "session": public_session_payload(staged),
            "export_format": export_format,
            "csv_path": export_paths.get("csv_path"),
            "pdf_path": export_paths.get("pdf_path"),
            "downloadable_artifacts": downloadable_artifacts,
            "download_markdown": build_download_markdown(downloadable_artifacts),
            "download_instructions": "Use clickable markdown links below.",
        }
    except SystemExit as exc:
        return {"status": "error", "message": str(exc)}
    except Exception as exc:
        return {"status": "error", "message": f"Export failed: {exc}"}


def show_current_configuration(tool_context: ToolContext | None = None) -> dict:
    configuration = load_session_configuration(tool_context)
    if not configuration:
        return {"status": "error", "message": "This session is not configured yet."}
    staged = load_staged_session(tool_context)
    return {
        "status": "success",
        "message": "Current session configuration loaded.",
        "configuration": configuration,
        "rescan_required": load_rescan_required(tool_context),
        "configuration_change_summary": load_config_change_summary(tool_context),
        "raw_jobs_available": has_raw_jobs(staged),
        "scored_results_available": has_cached_scan(staged),
        "session": public_session_payload(staged),
    }


def show_scan_status(tool_context: ToolContext | None = None) -> dict:
    try:
        staged = load_staged_session(tool_context)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc)}
    configuration = load_session_configuration(tool_context) or {}
    scan_status = read_scan_status(staged.state_dir)
    if scan_status:
        return {"status": "success", "message": str(scan_status.get("message") or "Scan status loaded."), "session": public_session_payload(staged), "scan_status": scan_status}
    if has_cached_scan(staged) and configuration:
        summary = build_scan_summary(staged, configuration, read_cached_scan(staged))
        return {
            "status": "success",
            "message": "No active scout or evaluator run is in progress. Returning last completed evaluation summary.",
            "session": public_session_payload(staged),
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
    if has_raw_jobs(staged):
        raw_jobs = read_raw_jobs(staged.state_dir)
        return {
            "status": "success",
            "message": "Discovered jobs are ready for evaluation.",
            "session": public_session_payload(staged),
            "scan_status": {
                "status": "completed",
                "phase": "discovered",
                "message": "Scouting is complete and jobs are waiting for evaluation.",
                "jobs_discovered_total": len(raw_jobs),
                "raw_jobs_path": str(staged.state_dir / RAW_JOBS_FILE_NAME),
            },
        }
    return {"status": "error", "message": "No scout or evaluator status is available yet. Run scouting first.", "session": public_session_payload(staged)}

