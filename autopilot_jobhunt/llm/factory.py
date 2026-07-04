from __future__ import annotations

import os
from typing import Any

from .base import LLMProviderService, string_value
from .providers import GoogleAdkService, NvidiaAdkService, OllamaAdkService


_REGISTERED_PROVIDER_SERVICES: tuple[type[LLMProviderService], ...] = (
    GoogleAdkService,
    NvidiaAdkService,
    OllamaAdkService,
)


def get_registered_provider_services() -> tuple[type[LLMProviderService], ...]:
    return _REGISTERED_PROVIDER_SERVICES


def get_configured_provider(config: dict[str, Any]) -> str:
    return string_value(os.getenv("ADK_MODEL_PROVIDER"), config.get("llm_provider"), "google").lower()


def get_provider_service_class(provider: str) -> type[LLMProviderService]:
    normalized = provider.strip().lower()
    for service_class in _REGISTERED_PROVIDER_SERVICES:
        if service_class.matches_provider(normalized):
            return service_class
    supported = sorted(alias for service_class in _REGISTERED_PROVIDER_SERVICES for alias in service_class.provider_names)
    raise ValueError(f"Unsupported ADK llm provider '{provider}'. Supported: {', '.join(supported)}")


def bootstrap_provider_environment(config: dict[str, Any]) -> None:
    for service_class in _REGISTERED_PROVIDER_SERVICES:
        service_class.bootstrap_environment(config)


def copy_provider_settings(*, provider: str, source_config: dict[str, Any], target_config: dict[str, Any]) -> None:
    try:
        service_class = get_provider_service_class(provider)
    except ValueError:
        return
    service_class.copy_session_config(source_config, target_config)


def create_llm_service(config: dict[str, Any]) -> LLMProviderService:
    return get_provider_service_class(get_configured_provider(config))(config)

