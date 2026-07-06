from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .paths import get_repo_root
from .text import sanitize_nested_strings, stripped_env


APP_NAME = "autopilot_jobhunt"

_PLACEHOLDERS = {
    "YOUR_TINYFISH_API_KEY",
    "your_tinyfish_api_key_here",
    "YOUR_OPENROUTER_API_KEY",
    "your_openrouter_api_key_here",
    "YOUR_NVIDIA_API_KEY",
    "your_nvidia_api_key_here",
    "YOUR_ANTHROPIC_API_KEY",
    "your_anthropic_api_key_here",
}

_ENV_MAPPING = {
    "TINYFISH_API_KEY": "tinyfish_api_key",
    "LLM_PROVIDER": "llm_provider",
    "OPENROUTER_API_KEY": "openrouter_api_key",
    "OPENROUTER_MODEL": "openrouter_model",
    "OPENROUTER_FALLBACK_MODELS": "openrouter_fallback_models",
    "NVIDIA_API_KEY": "nvidia_api_key",
    "NVIDIA_MODEL": "nvidia_model",
    "NVIDIA_FALLBACK_MODELS": "nvidia_fallback_models",
    "GOOGLE_API_KEY": "google_api_key",
    "GOOGLE_MODEL": "google_model",
    "GOOGLE_FALLBACK_MODELS": "google_fallback_models",
    "Z_AI_API_KEY": "z_ai_api_key",
    "Z_AI_MODEL": "z_ai_model",
    "Z_AI_FALLBACK_MODELS": "z_ai_fallback_models",
    "ZEN_API_KEY": "opencode_zen_api_key",
    "ZEN_BASE_URL": "opencode_zen_base_url",
    "ZEN_MODEL": "opencode_zen_model",
    "ZEN_FALLBACK_MODELS": "opencode_zen_fallback_models",
    "OLLAMA_API_KEY": "ollama_api_key",
    "OLLAMA_BASE_URL": "ollama_base_url",
    "OLLAMA_MODEL": "ollama_model",
    "OLLAMA_MAX_TOKENS": "ollama_max_tokens",
    "OLLAMA_FALLBACK_MODELS": "ollama_fallback_models",
}

_LIST_ENV_KEYS = {
    "OPENROUTER_FALLBACK_MODELS",
    "NVIDIA_FALLBACK_MODELS",
    "GOOGLE_FALLBACK_MODELS",
    "Z_AI_FALLBACK_MODELS",
    "ZEN_FALLBACK_MODELS",
    "OLLAMA_FALLBACK_MODELS",
}


def _is_placeholder(value: str) -> bool:
    return value in _PLACEHOLDERS or value.startswith("YOUR_") or value.endswith("_HERE") or value.endswith("_here")


def _use_env(value: str | None) -> bool:
    return bool(value) and not _is_placeholder(value)


def _config_path() -> Path | None:
    repo_root = get_repo_root()
    for filename in ("config.json", "config.example.json"):
        path = repo_root / filename
        if path.exists():
            return path
    return None


def load_repo_config() -> dict[str, Any]:
    config_path = _config_path()
    if config_path is None:
        return {}

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    config = sanitize_nested_strings(payload) if isinstance(payload, dict) else {}
    for env_key, config_key in _ENV_MAPPING.items():
        value = stripped_env(env_key)
        if not _use_env(value):
            continue
        if env_key in _LIST_ENV_KEYS:
            config[config_key] = [item.strip() for item in value.split(",") if item.strip()]
        else:
            config[config_key] = value
    return config


def resolve_tinyfish_api_key() -> str:
    repo_config = load_repo_config()
    config_key = str(repo_config.get("tinyfish_api_key") or "").strip()
    if config_key:
        return config_key
    return str(os.getenv("TINYFISH_API_KEY") or "").strip()
