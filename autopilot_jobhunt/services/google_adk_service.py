from __future__ import annotations

import os
from typing import Any

from .llm_provider_base import LLMProviderService, string_value


class GoogleAdkService(LLMProviderService):
    provider_names = ("google",)
    session_config_keys = ("google_model", "google_fallback_models")

    @classmethod
    def bootstrap_environment(cls, config: dict[str, Any]) -> None:
        google_api_key = string_value(config.get("google_api_key"))
        if google_api_key and not os.getenv("GOOGLE_API_KEY") and not os.getenv("GEMINI_API_KEY"):
            os.environ["GOOGLE_API_KEY"] = google_api_key

        google_model = string_value(config.get("google_model"))
        if google_model and not os.getenv("GOOGLE_GENAI_MODEL") and not os.getenv("ADK_MODEL"):
            os.environ["GOOGLE_GENAI_MODEL"] = google_model

    def create_model(self) -> Any:
        return string_value(
            os.getenv("ADK_MODEL"),
            os.getenv("GOOGLE_GENAI_MODEL"),
            self.config.get("google_model"),
            "gemini-3.5-flash",
        )
