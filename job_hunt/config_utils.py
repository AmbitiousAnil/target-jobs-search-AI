from __future__ import annotations

import os
from typing import Any


def stripped_text(value: Any) -> str:
    return str(value or "").strip()


def first_stripped(*values: Any, default: str = "") -> str:
    for value in values:
        text = stripped_text(value)
        if text:
            return text
    return default


def stripped_env(name: str, default: str = "") -> str:
    return first_stripped(os.getenv(name), default=default)


def sanitize_nested_strings(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return [sanitize_nested_strings(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_nested_strings(item) for item in value)
    if isinstance(value, dict):
        return {key: sanitize_nested_strings(item) for key, item in value.items()}
    return value
