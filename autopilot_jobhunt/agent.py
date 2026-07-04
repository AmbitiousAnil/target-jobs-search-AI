from __future__ import annotations

try:
    from google.adk import Agent
except Exception:  # pragma: no cover
    from google.adk.agents import Agent  # type: ignore[no-redef]

try:
    from google.adk.apps import App
except Exception:  # pragma: no cover
    from google.adk.apps.app import App  # type: ignore[no-redef]

try:
    from google.adk.plugins.save_files_as_artifacts_plugin import SaveFilesAsArtifactsPlugin
except Exception:  # pragma: no cover
    SaveFilesAsArtifactsPlugin = None  # type: ignore[assignment]

from .config.loader import APP_NAME, load_repo_config
from .llm.factory import bootstrap_provider_environment, create_llm_service
from .prompts import MASTER_INSTRUCTION
from .tools import (
    configure_candidate_search,
    export_results,
    scan_company_jobs,
    score_and_rank_jobs,
    show_current_configuration,
    show_scan_status,
    tailor_application_materials,
)


def _build_adk_model():
    config = load_repo_config()
    bootstrap_provider_environment(config)
    return create_llm_service(config).create_model()


root_agent = Agent(
    name=APP_NAME,
    model=_build_adk_model(),
    description=(
        "Session-aware single-agent job-hunt assistant that coordinates configuration, "
        "job discovery, scoring, tailoring, and export through explicit tool handoffs."
    ),
    instruction=MASTER_INSTRUCTION,
    tools=[
        configure_candidate_search,
        scan_company_jobs,
        score_and_rank_jobs,
        tailor_application_materials,
        export_results,
        show_current_configuration,
        show_scan_status,
    ],
)


app = App(
    name=APP_NAME,
    root_agent=root_agent,
    plugins=[SaveFilesAsArtifactsPlugin()] if SaveFilesAsArtifactsPlugin else [],
)
