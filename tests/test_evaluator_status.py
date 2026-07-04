import json

from autopilot_jobhunt.services import score_service
from autopilot_jobhunt.tools import job_tools


def test_run_evaluator_updates_jobs_scored_total_after_each_unique_job(tmp_path, monkeypatch):
    staged = job_tools.StagedSession(
        session_id="session-1",
        session_dir=tmp_path / "session-1",
        resume_path=tmp_path / "session-1" / "resume.md",
        companies_path=tmp_path / "session-1" / "companies.json",
        config_path=tmp_path / "session-1" / "config.json",
        manifest_path=tmp_path / "session-1" / "manifest.json",
        state_dir=tmp_path / "session-1" / "state",
        output_dir=tmp_path / "session-1" / "output",
    )
    staged.state_dir.mkdir(parents=True, exist_ok=True)
    staged.output_dir.mkdir(parents=True, exist_ok=True)
    staged.resume_path.write_text("resume text", encoding="utf-8")
    (staged.state_dir / job_tools.RAW_JOBS_FILE_NAME).write_text(
        json.dumps(
            [
                {"url": "https://example.com/1", "title": "Role 1", "company": "Example", "location": "Remote"},
                {"url": "https://example.com/2", "title": "Role 2", "company": "Example", "location": "Remote"},
            ]
        ),
        encoding="utf-8",
    )

    status_snapshots: list[dict] = []

    def fake_write_scan_status(state_dir, payload):
        del state_dir
        status_snapshots.append(payload.copy())
        return staged.state_dir / "scan_status.json"

    def fake_score_jobs(jobs, resume_text, runtime_config, on_job_started=None, on_scored_job=None):
        del resume_text, runtime_config
        for idx, job in enumerate(jobs, 1):
            if on_job_started:
                on_job_started(idx, job, len(jobs))
            scored_job = job | {
                "score": 80 + idx,
                "extracted_title": f"Scored {idx}",
                "reason": "fit",
                "worth_applying": True,
            }
            if on_scored_job:
                on_scored_job(scored_job)
        return [
            jobs[0] | {"score": 81, "extracted_title": "Scored 1", "reason": "fit", "worth_applying": True},
            jobs[1] | {"score": 82, "extracted_title": "Scored 2", "reason": "fit", "worth_applying": True},
        ]

    monkeypatch.setattr(score_service, "write_scan_status", fake_write_scan_status)
    monkeypatch.setattr(score_service, "score_jobs", fake_score_jobs)
    monkeypatch.setattr(score_service, "write_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(score_service, "read_job_history", lambda state_dir: [])

    runtime_config = {"candidate": {"min_score": 60}}
    scored_jobs, completed_status = score_service.run_evaluator_for_session(staged, runtime_config)

    assert len(scored_jobs) == 2
    assert completed_status["jobs_scored_total"] == 2
    assert any(snapshot.get("jobs_scored_total") == 1 for snapshot in status_snapshots)
    assert any(snapshot.get("jobs_scored_total") == 2 for snapshot in status_snapshots)
