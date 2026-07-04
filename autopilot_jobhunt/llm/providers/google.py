from __future__ import annotations

import os

from ..base import LLMProviderService, string_value


class GoogleAdkService(LLMProviderService):
    provider_names = ("google", "gemini")
    session_config_keys = ("google_api_key", "google_model", "google_fallback_models")

    @classmethod
    def bootstrap_environment(cls, config: dict[str, object]) -> None:
        api_key = string_value(os.getenv("GOOGLE_API_KEY"), config.get("google_api_key"))
        if api_key:
            os.environ["GOOGLE_API_KEY"] = api_key

    def create_model(self) -> str:
        return string_value(self.config.get("google_model"), "gemini-2.5-flash")

