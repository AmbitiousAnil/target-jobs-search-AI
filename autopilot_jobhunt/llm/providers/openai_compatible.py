from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod

from openai import OpenAI, RateLimitError

from ...config.text import first_stripped


_LLM_REQUEST_TIMEOUT = 120.0


def _format_exception_details(exc: Exception) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{current.__class__.__name__}: {str(current).strip() or '<no message>'}")
        current = current.__cause__ or current.__context__
    return " | caused by ".join(parts)


def _looks_placeholder(value: str) -> bool:
    return value.startswith("YOUR_") or value.endswith("_HERE") or value.endswith("_here") or value.lower().startswith("your_")


class LLMService(ABC):
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def chat(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        raise NotImplementedError


class OpenAICompatibleService(LLMService):
    provider_label = "OpenAI-compatible"
    api_key_config_key = ""
    api_key_env_key = ""
    base_url = ""
    model_config_key = ""
    fallback_models_config_key = ""
    default_model = ""

    def _api_key(self) -> str:
        api_key = first_stripped(self.config.get(self.api_key_config_key), os.getenv(self.api_key_env_key))
        if not api_key or _looks_placeholder(api_key):
            raise RuntimeError(f"{self.api_key_env_key} not set. Add it to config.json or .env.")
        return api_key

    def _client(self) -> OpenAI:
        return OpenAI(api_key=self._api_key(), base_url=self.base_url, timeout=_LLM_REQUEST_TIMEOUT)

    def _models(self) -> list[str]:
        primary = first_stripped(self.config.get(self.model_config_key), self.default_model)
        fallbacks = self.config.get(self.fallback_models_config_key) or []
        if isinstance(fallbacks, str):
            fallbacks = [item.strip() for item in fallbacks.split(",")]
        normalized = [first_stripped(item) for item in fallbacks]
        return [primary] + [item for item in normalized if item and item != primary]

    def chat(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        return chat_with_openai_models(self._client(), self.provider_label, self._models(), messages, temperature, max_tokens)


class OpenRouterService(OpenAICompatibleService):
    provider_label = "OpenRouter"
    api_key_config_key = "openrouter_api_key"
    api_key_env_key = "OPENROUTER_API_KEY"
    base_url = "https://openrouter.ai/api/v1"
    model_config_key = "openrouter_model"
    fallback_models_config_key = "openrouter_fallback_models"
    default_model = "nvidia/nemotron-3-super-120b-a12b:free"


class NvidiaService(OpenAICompatibleService):
    provider_label = "Nvidia"
    api_key_config_key = "nvidia_api_key"
    api_key_env_key = "NVIDIA_API_KEY"
    base_url = "https://integrate.api.nvidia.com/v1"
    model_config_key = "nvidia_model"
    fallback_models_config_key = "nvidia_fallback_models"
    default_model = "nvidia/llama-3.3-nemotron-super-49b-v1"


class GoogleService(OpenAICompatibleService):
    provider_label = "Google"
    api_key_config_key = "google_api_key"
    api_key_env_key = "GOOGLE_API_KEY"
    base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    model_config_key = "google_model"
    fallback_models_config_key = "google_fallback_models"
    default_model = "gemini-2.5-flash"


class ZaiService(OpenAICompatibleService):
    provider_label = "Z.ai"
    api_key_config_key = "z_ai_api_key"
    api_key_env_key = "Z_AI_API_KEY"
    base_url = "https://api.z.ai/api/paas/v4/"
    model_config_key = "z_ai_model"
    fallback_models_config_key = "z_ai_fallback_models"
    default_model = "glm-4.5-air"


class ZenService(OpenAICompatibleService):
    provider_label = "OpenCode Zen"
    api_key_config_key = "opencode_zen_api_key"
    api_key_env_key = "ZEN_API_KEY"
    base_url = "https://opencode.ai/zen/v1"
    model_config_key = "opencode_zen_model"
    fallback_models_config_key = "opencode_zen_fallback_models"
    default_model = "qwen-3.6-plus-free"

    def _client(self) -> OpenAI:
        return OpenAI(
            api_key=self._api_key(),
            base_url=first_stripped(self.config.get("opencode_zen_base_url"), os.getenv("ZEN_BASE_URL"), default=self.base_url),
            timeout=_LLM_REQUEST_TIMEOUT,
        )


class OllamaService(OpenAICompatibleService):
    provider_label = "Ollama"
    api_key_config_key = "ollama_api_key"
    api_key_env_key = "OLLAMA_API_KEY"
    model_config_key = "ollama_model"
    fallback_models_config_key = "ollama_fallback_models"
    default_model = "gemma4fable"

    def _api_key(self) -> str:
        return first_stripped(self.config.get(self.api_key_config_key), os.getenv(self.api_key_env_key), default="ollama")

    def _client(self) -> OpenAI:
        return OpenAI(
            api_key=self._api_key(),
            base_url=first_stripped(self.config.get("ollama_base_url"), os.getenv("OLLAMA_BASE_URL"), default="http://localhost:11434/v1"),
            timeout=_LLM_REQUEST_TIMEOUT,
        )

    def chat(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        configured_max_tokens = int(first_stripped(self.config.get("ollama_max_tokens"), os.getenv("OLLAMA_MAX_TOKENS"), default="8192"))
        return chat_with_openai_models(self._client(), self.provider_label, self._models(), messages, temperature, max(max_tokens, configured_max_tokens))


def create_chat_service(config: dict) -> LLMService:
    provider = first_stripped(config.get("llm_provider"), default="openrouter").lower()
    services = {
        "openrouter": OpenRouterService,
        "nvidia": NvidiaService,
        "google": GoogleService,
        "zai": ZaiService,
        "z_ai": ZaiService,
        "zen": ZenService,
        "opencode_zen": ZenService,
        "opencode-zen": ZenService,
        "ollama": OllamaService,
    }
    try:
        return services[provider](config)
    except KeyError:
        raise ValueError(f"Unsupported llm_provider '{provider}'. Supported: {', '.join(sorted(services))}") from None


def chat_with_openai_models(llm: OpenAI, provider_label: str, models: list[str], messages: list[dict], temperature: float = 0.1, max_tokens: int = 4096) -> str:
    if not models:
        raise RuntimeError(f"No models configured for {provider_label}.")
    for model in models:
        requested_max_tokens = max_tokens
        for attempt in range(2):
            try:
                resp = llm.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=requested_max_tokens,
                )
                choice = resp.choices[0]
                text = choice.message.content or ""
                reasoning = getattr(choice.message, "reasoning", "") or ""
                finish_reason = getattr(choice, "finish_reason", "")
                if not text.strip() and reasoning and finish_reason == "length" and attempt == 0:
                    requested_max_tokens = min(max(requested_max_tokens * 2, requested_max_tokens + 256), 8192)
                    continue
                if not text.strip() and reasoning:
                    raise RuntimeError(f"{provider_label} returned reasoning but no final content.")
                return text
            except RateLimitError:
                if attempt == 0:
                    time.sleep(3)
                    continue
                break
            except Exception as exc:
                raise RuntimeError(f"LLM error for {provider_label} model {model}: {_format_exception_details(exc)}") from exc
    raise RuntimeError(f"All {provider_label} LLM models failed.")
