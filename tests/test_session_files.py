import json

from autopilot_jobhunt.services import session_files
from autopilot_jobhunt.services.session_files import (
    JobSearchConfiguration,
    stage_session_files,
)


def test_stage_session_files_creates_isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_ADK_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("TINYFISH_API_KEY", "secret-should-not-be-written")
    monkeypatch.setattr(session_files, "_load_repo_config", lambda: {"tinyfish_api_key": ""})

    config = JobSearchConfiguration(
        resume_text="Senior ML engineer with Python and LLM experience.",
        company_urls=[
            "https://careers.example.com/jobs",
            "https://careers.example.com/jobs",
            "https://jobs.secondco.ai/openings",
        ],
        target_roles=["ML Engineer", "AI Engineer"],
        target_locations=["Germany", "Remote"],
        min_score=70,
        top_n=3,
        llm_provider_override="openrouter",
    )

    staged = stage_session_files("session:alpha", config)

    assert staged.session_dir == tmp_path / "runtime" / "sessions" / "session-alpha"
    assert staged.resume_path.exists()
    assert staged.companies_path.exists()
    assert staged.config_path.exists()
    assert staged.output_dir.exists()
    assert staged.state_dir.exists()

    written_config = json.loads(staged.config_path.read_text(encoding="utf-8"))
    written_companies = json.loads(staged.companies_path.read_text(encoding="utf-8"))

    assert written_config["tinyfish_api_key"] == ""
    assert written_config["candidate"]["resume_path"] == "resume.md"
    assert written_config["candidate"]["min_score"] == 70
    assert written_config["candidate"]["top_n"] == 3
    assert written_config["candidate"]["countries"] == ["Germany", "Remote"]
    assert written_config["llm_provider"] == "openrouter"
    assert len(written_companies) == 2
def test_stage_session_files_inherits_nvidia_model_settings_from_repo_config(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_ADK_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setattr(
        session_files,
        "_load_repo_config",
        lambda: {
            "tinyfish_api_key": "",
            "llm_provider": "nvidia",
            "nvidia_model": "nvidia/nemotron-3-nano-30b-a3b",
            "nvidia_fallback_models": ["google/gemma-4-31b-itb", "meta/llama-3.1-8b-instruct"],
        },
    )

    config = JobSearchConfiguration(
        resume_text="Senior ML engineer with Python and LLM experience.",
        company_urls=["https://careers.example.com/jobs"],
        target_roles=["ML Engineer"],
        target_locations=["Germany"],
    )

    staged = stage_session_files("session:nvidia", config)
    written_config = json.loads(staged.config_path.read_text(encoding="utf-8"))

    assert written_config["llm_provider"] == "nvidia"
    assert written_config["nvidia_model"] == "nvidia/nemotron-3-nano-30b-a3b"
    assert written_config["nvidia_fallback_models"] == [
        "google/gemma-4-31b-itb",
        "meta/llama-3.1-8b-instruct",
    ]


def test_stage_session_files_rejects_invalid_company_urls(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_ADK_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setattr(session_files, "_load_repo_config", lambda: {"tinyfish_api_key": ""})

    config = JobSearchConfiguration(
        resume_text="resume",
        company_urls=["careers.example.com/jobs"],
        target_roles=["Engineer"],
        target_locations=["India"],
    )

    try:
        stage_session_files("bad-session", config)
    except ValueError as exc:
        assert "http/https" in str(exc)
    else:
        raise AssertionError("Expected invalid URL validation to fail.")
