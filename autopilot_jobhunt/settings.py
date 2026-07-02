from __future__ import annotations

import os
from typing import Any

from .app_paths import (
    load_repo_config,
)
from .services.llm_factory import bootstrap_provider_environment, create_llm_service


APP_NAME = "autopilot_jobhunt"


def _load_repo_config() -> dict:
    return load_repo_config()


_REPO_CONFIG = _load_repo_config()
bootstrap_provider_environment(_REPO_CONFIG)


def get_adk_model() -> Any:
    return create_llm_service(_REPO_CONFIG).create_model()
