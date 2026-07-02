from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .session_files import StagedSession


def get_tailoring_skill_root() -> Path:
    return Path(__file__).resolve().parents[2] / "skills" / "job-application-tailor"


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def load_tailoring_guidance() -> dict[str, str]:
    skill_root = get_tailoring_skill_root()
    return {
        "skill_name": "job-application-tailor",
        "skill_path": str(skill_root),
        "skill_overview": _read_text_if_exists(skill_root / "SKILL.md"),
        "resume_guidance": _read_text_if_exists(skill_root / "references" / "resume-tailoring.md"),
        "cover_letter_guidance": _read_text_if_exists(skill_root / "references" / "cover-letter-tailoring.md"),
        "application_checklist": _read_text_if_exists(skill_root / "assets" / "application-output-checklist.md"),
    }


def write_tailoring_skill_manifest(
    output_dir: Path,
    *,
    staged: StagedSession,
    job_ref: str,
    guidance: dict[str, str],
    selected_job: dict[str, Any] | None = None,
) -> Path:
    manifest = {
        "skill_name": guidance.get("skill_name"),
        "skill_path": guidance.get("skill_path"),
        "job_ref": job_ref,
        "session_id": staged.session_id,
        "session_dir": str(staged.session_dir),
        "selected_job": selected_job or {},
        "references_used": [
            "references/resume-tailoring.md",
            "references/cover-letter-tailoring.md",
            "assets/application-output-checklist.md",
        ],
    }
    manifest_path = output_dir / "tailoring_skill_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path
