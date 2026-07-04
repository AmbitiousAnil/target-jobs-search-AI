from __future__ import annotations

from ..domain.models import StagedSession
from ..export.csv import export_jobs
from ..storage.scan_state import read_job_history, read_last_scan


def run_export_for_session(staged: StagedSession, min_score: int, days: int, export_format: str) -> dict[str, str | None]:
    return export_jobs(
        jobs=read_last_scan(staged.state_dir),
        history_jobs=read_job_history(staged.state_dir),
        min_score=min_score,
        days=days,
        export_format=export_format,
        output_dir=staged.output_dir,
    )
