from __future__ import annotations

import os
from typing import Any

from .llm_provider_base import LiteLlmAdkService, string_value


class NvidiaAdkService(LiteLlmAdkService):
    provider_label = "Nvidia"
    provider_names = ("nvidia",)
    session_config_keys = (
        "nvidia_model",
        "nvidia_fallback_models",
    )

    @classmethod
    def bootstrap_environment(cls, config: dict[str, Any]) -> None:
        nvidia_api_key = string_value(config.get("nvidia_api_key"))
        if nvidia_api_key and not os.getenv("NVIDIA_API_KEY"):
            os.environ["NVIDIA_API_KEY"] = nvidia_api_key

    def create_model(self) -> Any:
        api_key = string_value(
            os.getenv("NVIDIA_API_KEY"),
            self.config.get("nvidia_api_key"),
        )
        model = string_value(
            self.config.get("nvidia_model"),
            os.getenv("NVIDIA_MODEL"),
            "google/gemma-4-31b-it",
        )
        return self._create_litellm(
            model=model,
            api_key=api_key,
            api_base="https://integrate.api.nvidia.com/v1",
        )
