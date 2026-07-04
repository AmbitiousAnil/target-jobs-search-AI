from __future__ import annotations

from .providers.openai_compatible import create_chat_service


def chat_with_llm(config: dict, messages: list[dict], temperature: float = 0.1, max_tokens: int = 4096) -> str:
    return create_chat_service(config).chat(messages, temperature, max_tokens)
