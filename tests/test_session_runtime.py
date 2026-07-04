from autopilot_jobhunt.domain.models import JobSearchConfiguration
from autopilot_jobhunt.storage.session_files import stage_session_files
from autopilot_jobhunt.storage.session_state import (
    load_config_change_summary,
    load_internal_session_configuration,
    load_rescan_required,
    load_session_configuration,
    persist_session_configuration,
    update_rescan_state,
)


class FakeToolContext:
    def __init__(self, session_id: str, *, with_state: bool = True):
        self.session_id = session_id
        if with_state:
            self.state = {}


def test_session_runtime_recovers_persisted_configuration_from_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_ADK_RUNTIME_ROOT", str(tmp_path / "runtime"))

    config = JobSearchConfiguration(
        resume_text="resume text",
        company_urls=["https://careers.example.com/jobs"],
        target_roles=["Staff Engineer"],
        target_locations=["Remote"],
        min_score=70,
        top_n=4,
    )
    staged = stage_session_files("session:recover", config)

    original_context = FakeToolContext("session:recover")
    persist_session_configuration(
        original_context,
        config,
        staged,
        rescan_required=True,
        config_change_summary="Saved a new configuration. Run scouting and evaluation.",
    )

    recovered_context = FakeToolContext("session:recover", with_state=False)
    public_config = load_session_configuration(recovered_context)
    internal_config = load_internal_session_configuration(recovered_context)

    assert public_config is not None
    assert public_config["session_dir"] == str(staged.session_dir)
    assert public_config["target_roles"] == ["Staff Engineer"]
    assert internal_config is not None
    assert internal_config["resume_text"] == "resume text"
    assert load_rescan_required(recovered_context) is True
    assert load_config_change_summary(recovered_context) == "Saved a new configuration. Run scouting and evaluation."


def test_update_rescan_state_updates_disk_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_ADK_RUNTIME_ROOT", str(tmp_path / "runtime"))

    config = JobSearchConfiguration(
        resume_text="resume text",
        company_urls=["https://careers.example.com/jobs"],
        target_roles=["Engineer"],
        target_locations=["USA"],
    )
    staged = stage_session_files("session:update", config)

    original_context = FakeToolContext("session:update")
    persist_session_configuration(
        original_context,
        config,
        staged,
        rescan_required=True,
        config_change_summary="Initial config",
    )

    recovered_context = FakeToolContext("session:update", with_state=False)
    update_rescan_state(
        recovered_context,
        rescan_required=False,
        config_change_summary="Using cached scored jobs from the last completed evaluation.",
    )

    assert load_rescan_required(recovered_context) is False
    assert load_config_change_summary(recovered_context) == "Using cached scored jobs from the last completed evaluation."
