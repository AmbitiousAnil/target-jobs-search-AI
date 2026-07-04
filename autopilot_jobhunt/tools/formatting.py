from __future__ import annotations

from typing import Any

from ..domain.models import StagedSession
from ..services.config_service import public_session_payload
from ..services.score_service import build_scan_summary


def score_selection_prompt(summary: dict[str, Any]) -> str:
    top_matches = list(summary.get("top_matches") or [])
    if not top_matches:
        return (
            f"No jobs met min_score {summary['min_score']}. "
            "Lower min_score and run scoring again if you want broader matches."
        )
    return (
        "Reply with job_ref for role you want to tailor, "
        f"for example {top_matches[0]['job_ref']}. I will generate tailored resume and cover letter for that job."
    )


def score_result_message(summary: dict[str, Any]) -> str:
    matched_jobs = int(summary["above_threshold_jobs"])
    total_jobs = int(summary["scored_jobs"])
    min_score = int(summary["min_score"])
    if not matched_jobs:
        return (
            f"Scoring complete. {total_jobs} jobs were scored and 0 met min_score {min_score}. "
            "Lower min_score and rerun scoring if you want more matches."
        )
    return (
        f"Scoring complete. {total_jobs} jobs were scored and {matched_jobs} met min_score {min_score}. "
        f"Showing the top {len(summary['top_matches'])} matched job(s). {score_selection_prompt(summary)}"
    )


def selection_option_label(match: dict[str, Any]) -> str:
    return f"{match['job_ref']} - {match.get('title') or 'Untitled role'} at {match.get('company') or 'Unknown company'} (score: {match.get('score')})"


def build_selection_options(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "job_ref": match["job_ref"],
            "label": selection_option_label(match),
            "score": match.get("score"),
            "title": match.get("title"),
            "company": match.get("company"),
            "location": match.get("location"),
            "url": match.get("url"),
        }
        for match in list(summary.get("top_matches") or [])
    ]


def score_results_markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"Scoring complete. {summary['scored_jobs']} jobs were scored.",
        f"Jobs meeting min_score {summary['min_score']}: {summary['above_threshold_jobs']}.",
    ]
    top_matches = list(summary.get("top_matches") or [])
    if not top_matches:
        lines.append("No matched jobs yet. Lower min_score and rerun scoring if you want broader matches.")
        return "\n".join(lines)
    lines.extend(["", "Top matched jobs:"])
    for match in top_matches:
        lines.append(
            f"- {match['job_ref']} | score {match.get('score')} | {match.get('title') or 'Untitled role'} | {match.get('company') or 'Unknown company'} | {match.get('location') or 'Location not listed'}"
        )
    lines.extend(["", "Pick one job_ref from list above for tailoring:"])
    for option in build_selection_options(summary):
        lines.append(f"- {option['job_ref']}: tailor resume and cover letter for {option['title']} at {option['company']}")
    lines.extend(["", score_selection_prompt(summary)])
    return "\n".join(lines)


def build_scored_jobs_response(staged: StagedSession, configuration: dict, jobs: list[dict], *, status_message: str, used_cached_results: bool) -> dict:
    summary = build_scan_summary(staged, configuration, jobs)
    top_matches = list(summary["top_matches"])
    selection_options = build_selection_options(summary)
    return {
        "status": "success",
        "message": score_result_message(summary),
        "status_message": status_message,
        "used_cached_results": used_cached_results,
        "session": public_session_payload(staged),
        "scan_summary": summary,
        "results_markdown": score_results_markdown(summary),
        "matched_job_refs": [match["job_ref"] for match in top_matches],
        "selection_options": selection_options,
        "selection_prompt": score_selection_prompt(summary),
        "next_step": "tailor_application_materials" if summary["above_threshold_jobs"] > 0 else "configure_candidate_search",
    }
