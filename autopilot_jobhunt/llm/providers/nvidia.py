from __future__ import annotations

import os

from ..base import LiteLlmAdkService, string_value


class NvidiaAdkService(LiteLlmAdkService):
    provider_names = ("nvidia",)
    session_config_keys = ("nvidia_api_key", "nvidia_model", "nvidia_fallback_models")
    provider_label = "Nvidia"
    api_base = "https://integrate.api.nvidia.com/v1"

    @classmethod
    def bootstrap_environment(cls, config: dict[str, object]) -> None:
        api_key = string_value(os.getenv("NVIDIA_API_KEY"), config.get("nvidia_api_key"))
        if api_key:
            os.environ["NVIDIA_API_KEY"] = api_key
            # LiteLLM routes this through its OpenAI-compatible transport.
            os.environ["OPENAI_API_KEY"] = api_key
            os.environ["OPENAI_BASE_URL"] = cls.api_base
            os.environ["OPENAI_API_BASE"] = cls.api_base

    def create_model(self):
        return self._create_litellm(
            model=string_value(self.config.get("nvidia_model"), "nvidia/llama-3.3-nemotron-super-49b-v1"),
            api_key=string_value(os.getenv("NVIDIA_API_KEY"), self.config.get("nvidia_api_key")),
            api_base=self.api_base,
        )
