import asyncio
import json
from pathlib import Path

from autopilot_jobhunt.tools import job_tools


class FakeToolContext:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state = {}


def test_scan_fails_cleanly_before_configuration():
    result = job_tools.scan_company_jobs(tool_context=FakeToolContext("s-1"))
    assert result["status"] == "error"
    assert "configure_candidate_search" in result["message"]


def test_configure_then_scout_then_evaluate_then_tailor_and_export(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_ADK_RUNTIME_ROOT", str(tmp_path / "runtime"))

    def fake_scout(staged, runtime_config):
        jobs = [
            {
                "url": "https://example.com/jobs/1",
                "company": "Example",
                "title": "Machine Learning Engineer",
                "location": "Remote",
                "region": "Global",
                "content": "Python, LLMs, shipping ML systems",
            },
            {
                "url": "https://example.com/jobs/2",
                "company": "Second",
                "title": "Data Scientist",
                "location": "Berlin",
                "region": "Germany",
                "content": "Statistics, experimentation, dashboards",
            },
        ]
        raw_jobs_path = staged.state_dir / job_tools.RAW_JOBS_FILE_NAME
        raw_jobs_path.parent.mkdir(parents=True, exist_ok=True)
        raw_jobs_path.write_text(json.dumps(jobs), encoding="utf-8")
        status = {
            "status": "completed",
            "phase": "discovered",
            "message": "Scouting complete. 2 jobs are ready for evaluation.",
            "companies_total": 1,
        }
        return jobs, status

    def fake_evaluator(staged, runtime_config):
        jobs = [
            {
                "url": "https://example.com/jobs/1",
                "company": "Example",
                "title": "Machine Learning Engineer",
                "extracted_title": "Machine Learning Engineer",
                "score": 72,
                "location_remote": "Remote",
                "reason": "Strong ML systems and LLM fit.",
                "scan_date": "2026-06-29",
            },
            {
                "url": "https://example.com/jobs/2",
                "company": "Second",
                "title": "Data Scientist",
                "extracted_title": "Data Scientist",
                "score": 91,
                "location_remote": "Berlin",
                "reason": "Relevant analysis background but weaker LLM match.",
                "scan_date": "2026-06-29",
            },
        ]
        last_scan = staged.state_dir / "last_scan.json"
        last_scan.parent.mkdir(parents=True, exist_ok=True)
        last_scan.write_text(json.dumps(jobs), encoding="utf-8")
        return jobs, {
            "status": "completed",
            "phase": "completed",
            "message": "Evaluation complete. 2 jobs scored.",
        }

    def fake_tailor(staged, job_ref, runtime_config, guidance):
        out_dir = staged.output_dir / "example-2026-06-29"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "resume_example.md").write_text("tailored resume", encoding="utf-8")
        (out_dir / "cover_letter_example.md").write_text("cover letter", encoding="utf-8")
        (out_dir / "resume_example.pdf").write_bytes(b"%PDF-1.4 resume")
        (out_dir / "cover_letter_example.pdf").write_bytes(b"%PDF-1.4 cover")
        return out_dir

    export_calls = []

    def fake_export(staged, min_score, days, export_format):
        export_calls.append((min_score, days, export_format, staged.session_id))
        csv_file = staged.output_dir / "jobs_2026-06-29_last7d.csv"
        pdf_file = staged.output_dir / "jobs_2026-06-29_last7d.pdf"
        csv_file.parent.mkdir(parents=True, exist_ok=True)
        csv_file.write_text("company,score\nExample,91\n", encoding="utf-8")
        pdf_file.write_bytes(b"%PDF-1.4 test pdf")
        return {
            "csv_path": str(csv_file) if export_format in {"csv", "both"} else None,
            "pdf_path": str(pdf_file) if export_format in {"pdf", "both"} else None,
        }

    monkeypatch.setattr(job_tools, "_run_scout_for_session", fake_scout)
    monkeypatch.setattr(job_tools, "_run_evaluator_for_session", fake_evaluator)
    monkeypatch.setattr(job_tools, "_run_tailoring_for_session", fake_tailor)
    monkeypatch.setattr(job_tools, "_run_export_for_session", fake_export)
    monkeypatch.setattr(
        job_tools,
        "load_tailoring_guidance",
        lambda: {
            "skill_name": "job-application-tailor",
            "skill_path": str(tmp_path / "skills" / "job-application-tailor"),
            "resume_guidance": "resume guidance",
            "cover_letter_guidance": "cover guidance",
            "application_checklist": "checklist",
        },
    )
    monkeypatch.setattr(
        job_tools,
        "write_tailoring_skill_manifest",
        lambda output_dir, **kwargs: output_dir / "tailoring_skill_manifest.json",
    )

    tool_context = FakeToolContext("session-42")

    configured = asyncio.run(
        job_tools.configure_candidate_search(
            resume_text="Senior AI engineer.",
            company_urls=["https://careers.example.com/jobs"],
            target_roles=["AI Engineer"],
            target_locations=["Germany"],
            min_score=65,
            top_n=4,
            tool_context=tool_context,
        )
    )
    assert configured["status"] == "success"
    assert configured["session"]["session_dir"].endswith("session-42")
    assert configured["next_step"] == "scan_company_jobs"

    scouted = job_tools.scan_company_jobs(tool_context=tool_context)
    assert scouted["status"] == "success"
    assert scouted["scout_summary"]["raw_jobs_count"] == 2
    assert scouted["next_step"] == "score_and_rank_jobs"

    evaluated = job_tools.score_and_rank_jobs(tool_context=tool_context)
    assert evaluated["status"] == "success"
    assert evaluated["scan_summary"]["total_jobs"] == 2
    assert evaluated["scan_summary"]["top_matches"][0]["score"] == 91
    assert evaluated["scan_summary"]["top_matches"][0]["job_ref"] == "#2"
    assert evaluated["next_step"] == "tailor_application_materials"
    assert "Reply with the job_ref" in evaluated["selection_prompt"]

    tailored = asyncio.run(
        job_tools.tailor_application_materials(
            evaluated["scan_summary"]["top_matches"][0]["job_ref"],
            tool_context=tool_context,
        )
    )
    assert tailored["status"] == "success"
    assert tailored["selected_job"]["job_ref"] == "#2"
    assert tailored["selected_job"]["url"] == "https://example.com/jobs/2"
    assert tailored["draft_output_dir"].endswith("example-2026-06-29")
    assert tailored["skill"]["name"] == "job-application-tailor"
    assert tailored["files"]["resume_pdf_path"].endswith("resume_example.pdf")
    assert tailored["files"]["cover_letter_pdf_path"].endswith("cover_letter_example.pdf")

    exported = asyncio.run(
        job_tools.export_results(
            min_score=80,
            days=7,
            export_format="both",
            tool_context=tool_context,
        )
    )
    assert exported["status"] == "success"
    assert exported["csv_path"].endswith("jobs_2026-06-29_last7d.csv")
    assert exported["pdf_path"].endswith("jobs_2026-06-29_last7d.pdf")
    assert export_calls == [(80, 7, "both", "session-42")]


def test_combined_scan_alias_runs_scout_then_evaluate(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_ADK_RUNTIME_ROOT", str(tmp_path / "runtime"))
    tool_context = FakeToolContext("session-99")

    asyncio.run(
        job_tools.configure_candidate_search(
            resume_text="resume text",
            company_urls=["https://careers.example.com/jobs"],
            target_roles=["ML Engineer"],
            target_locations=["Remote"],
            tool_context=tool_context,
        )
    )

    monkeypatch.setattr(
        job_tools,
        "scan_company_jobs",
        lambda tool_context=None: {"status": "success", "message": "scouted"},
    )
    monkeypatch.setattr(
        job_tools,
        "score_and_rank_jobs",
        lambda tool_context=None: {"status": "success", "message": "evaluated"},
    )

    result = job_tools.scan_configured_jobs(tool_context=tool_context)
    assert result["status"] == "success"
    assert result["message"] == "evaluated"


class FakeArtifactInlineData:
    def __init__(self, data: bytes):
        self.data = data


class FakeArtifact:
    def __init__(self, data: bytes):
        self.inline_data = FakeArtifactInlineData(data)


class FakeArtifactToolContext(FakeToolContext):
    def __init__(self, session_id: str):
        super().__init__(session_id)
        self._artifacts = {"resume.pdf": FakeArtifact(b"fake-pdf")}

    async def list_artifacts(self):
        return list(self._artifacts)

    async def load_artifact(self, filename: str):
        return self._artifacts.get(filename)


def test_configure_candidate_search_accepts_resume_pdf_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_ADK_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setattr(job_tools, "extract_text_from_pdf_bytes", lambda data: "Resume text from PDF")

    tool_context = FakeArtifactToolContext("session-pdf")
    result = asyncio.run(
        job_tools.configure_candidate_search(
            company_urls=["https://careers.example.com/jobs"],
            target_roles=["ML Engineer"],
            target_locations=["Remote"],
            resume_pdf_artifact="resume.pdf",
            tool_context=tool_context,
        )
    )

    assert result["status"] == "success"
    assert result["configuration"]["resume_source"]["type"] == "pdf_artifact"
    assert result["configuration"]["resume_source"]["artifact_name"] == "resume.pdf"
