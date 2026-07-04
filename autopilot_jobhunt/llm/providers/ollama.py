from __future__ import annotations

import os

from ..base import LiteLlmAdkService, string_value


class OllamaAdkService(LiteLlmAdkService):
    provider_names = ("ollama",)
    session_config_keys = ("ollama_api_key", "ollama_base_url", "ollama_model", "ollama_max_tokens", "ollama_fallback_models")
    provider_label = "Ollama"

    def create_model(self):
        return self._create_litellm(
            model=string_value(self.config.get("ollama_model"), "gemma4fable"),
            api_key=string_value(self.config.get("ollama_api_key"), os.getenv("OLLAMA_API_KEY"), "ollama"),
            api_base=string_value(self.config.get("ollama_base_url"), os.getenv("OLLAMA_BASE_URL"), "http://localhost:11434/v1"),
        )
