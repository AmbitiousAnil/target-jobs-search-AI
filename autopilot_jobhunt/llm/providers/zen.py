from __future__ import annotations

import os

from ..base import LiteLlmAdkService, string_value


class ZenAdkService(LiteLlmAdkService):
    provider_names = ("zen", "opencode_zen", "opencode-zen")
    session_config_keys = (
        "opencode_zen_api_key",
        "opencode_zen_base_url",
        "opencode_zen_model",
        "opencode_zen_fallback_models",
    )
    provider_label = "OpenCode Zen"
    default_api_base = "https://opencode.ai/zen/v1"
    default_model = "qwen-3.6-plus-free"

    @classmethod
    def bootstrap_environment(cls, config: dict[str, object]) -> None:
        api_key = string_value(os.getenv("ZEN_API_KEY"), config.get("opencode_zen_api_key"))
        api_base = string_value(config.get("opencode_zen_base_url"), os.getenv("ZEN_BASE_URL"), cls.default_api_base)
        if api_key:
            os.environ["ZEN_API_KEY"] = api_key
            # LiteLLM routes OpenAI-compatible providers through these env vars.
            os.environ["OPENAI_API_KEY"] = api_key
            os.environ["OPENAI_BASE_URL"] = api_base
            os.environ["OPENAI_API_BASE"] = api_base

    def create_model(self):
        return self._create_litellm(
            model=string_value(self.config.get("opencode_zen_model"), os.getenv("ZEN_MODEL"), self.default_model),
            api_key=string_value(os.getenv("ZEN_API_KEY"), self.config.get("opencode_zen_api_key")),
            api_base=string_value(
                self.config.get("opencode_zen_base_url"), os.getenv("ZEN_BASE_URL"), self.default_api_base
            ),
        )