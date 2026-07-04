from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


def string_value(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def normalize_config_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key.endswith("_fallback_models"):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return value


class LLMProviderService(ABC):
    provider_names: tuple[str, ...] = ()
    session_config_keys: tuple[str, ...] = ()

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @classmethod
    def matches_provider(cls, provider: str) -> bool:
        return provider.strip().lower() in cls.provider_names

    @classmethod
    def copy_session_config(cls, source_config: dict[str, Any], target_config: dict[str, Any]) -> None:
        for key in cls.session_config_keys:
            normalized = normalize_config_value(key, source_config.get(key))
            if normalized is not None:
                target_config[key] = normalized

    @classmethod
    def bootstrap_environment(cls, config: dict[str, Any]) -> None:
        del config

    @abstractmethod
    def create_model(self) -> Any:
        raise NotImplementedError


class LiteLlmAdkService(LLMProviderService):
    provider_label = "LiteLLM"

    def _load_litellm_class(self) -> Any:
        try:
            from google.adk.models import LiteLlm
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                f"{self.provider_label} support requires google-adk in runtime."
            ) from exc
        return LiteLlm

    def _create_litellm(self, *, model: str, api_key: str, api_base: str, extra_headers: dict[str, str] | None = None) -> Any:
        lite_llm = self._load_litellm_class()
        kwargs: dict[str, Any] = {
            "model": model if model.startswith("openai/") else f"openai/{model}",
            "api_key": api_key,
            "api_base": api_base,
        }
        if extra_headers:
            kwargs["extra_headers"] = extra_headers
        return lite_llm(**kwargs)

