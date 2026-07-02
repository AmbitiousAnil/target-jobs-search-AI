from __future__ import annotations

import os
from typing import Any

from .llm_provider_base import LiteLlmAdkService, string_value


class OllamaAdkService(LiteLlmAdkService):
    provider_label = "Ollama"
    provider_names = ("ollama",)
    session_config_keys = (
        "ollama_model",
        "ollama_fallback_models",
        "ollama_base_url",
        "ollama_max_tokens",
    )

    @classmethod
    def bootstrap_environment(cls, config: dict[str, Any]) -> None:
        ollama_api_key = string_value(config.get("ollama_api_key"))
        if ollama_api_key and not os.getenv("OLLAMA_API_KEY"):
            os.environ["OLLAMA_API_KEY"] = ollama_api_key

        ollama_base_url = string_value(config.get("ollama_base_url"))
        if ollama_base_url and not os.getenv("OLLAMA_BASE_URL"):
            os.environ["OLLAMA_BASE_URL"] = ollama_base_url

    def create_model(self) -> Any:
        api_key = string_value(
            os.getenv("OLLAMA_API_KEY"),
            self.config.get("ollama_api_key"),
            "ollama",
        )
        model = string_value(
            self.config.get("ollama_model"),
            os.getenv("OLLAMA_MODEL"),
            "gemma4fable",
        )
        api_base = string_value(
            self.config.get("ollama_base_url"),
            os.getenv("OLLAMA_BASE_URL"),
            "http://localhost:11434/v1",
        )
        return self._create_litellm(
            model=model,
            api_key=api_key,
            api_base=api_base,
        )
