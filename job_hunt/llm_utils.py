import json
import os
import subprocess
import time
from abc import ABC, abstractmethod

from openai import OpenAI, RateLimitError

from job_hunt.config_utils import first_stripped, stripped_env
from job_hunt.log import get_logger

logger = get_logger()

# Per-request timeout (seconds) for HTTP-based LLM providers. Without this the
# openai/anthropic SDKs default to 600s, so a single stalled free-tier model can
# freeze a scan for 10 minutes. claude_cli has its own subprocess timeout (300s).
_LLM_REQUEST_TIMEOUT = 120.0


def _format_exception_details(exc: Exception) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()

    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current).strip() or "<no message>"
        parts.append(f"{current.__class__.__name__}: {message}")
        current = current.__cause__ or current.__context__

    return " | caused by ".join(parts)


def _looks_placeholder(value: str) -> bool:
    return (
        value.startswith("YOUR_")
        or value.endswith("_HERE")
        or value.endswith("_here")
        or value.lower().startswith("your_")
    )


class LLMService(ABC):
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def chat(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        pass


class OpenAICompatibleService(LLMService):
    provider_label = "OpenAI-compatible"
    api_key_config_key = ""
    api_key_env_key = ""
    base_url = ""
    model_config_key = ""
    fallback_models_config_key = ""
    default_model = ""

    def _api_key(self) -> str:
        api_key = first_stripped(
            self.config.get(self.api_key_config_key),
            os.getenv(self.api_key_env_key),
        )
        if not api_key or _looks_placeholder(api_key):
            raise RuntimeError(
                f"{self.api_key_env_key} not set. Add it to config.json or your .env file."
            )
        return api_key

    def _client(self) -> OpenAI:
        return OpenAI(
            api_key=self._api_key(),
            base_url=self.base_url,
            timeout=_LLM_REQUEST_TIMEOUT,
        )

    def _models(self) -> list[str]:
        primary = first_stripped(self.config.get(self.model_config_key), self.default_model)
        fallbacks = self.config.get(self.fallback_models_config_key) or []
        if isinstance(fallbacks, str):
            fallbacks = [m.strip() for m in fallbacks.split(",")]
        normalized_fallbacks = [first_stripped(m) for m in fallbacks]
        return [primary] + [m for m in normalized_fallbacks if m and m != primary]

    def chat(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        return _chat_with_openai_models(
            self._client(),
            self.provider_label,
            self._models(),
            messages,
            temperature,
            max_tokens,
        )


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


class OllamaService(OpenAICompatibleService):
    provider_label = "Ollama"
    api_key_config_key = "ollama_api_key"
    api_key_env_key = "OLLAMA_API_KEY"
    model_config_key = "ollama_model"
    fallback_models_config_key = "ollama_fallback_models"
    default_model = "gemma4fable"

    def _api_key(self) -> str:
        return first_stripped(
            self.config.get(self.api_key_config_key),
            os.getenv(self.api_key_env_key),
            default="ollama",
        )

    def _client(self) -> OpenAI:
        base_url = first_stripped(
            self.config.get("ollama_base_url"),
            os.getenv("OLLAMA_BASE_URL"),
            default="http://localhost:11434/v1",
        )
        return OpenAI(
            api_key=self._api_key(),
            base_url=base_url,
            timeout=_LLM_REQUEST_TIMEOUT,
        )

    def chat(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        configured_max_tokens = int(first_stripped(
            self.config.get("ollama_max_tokens"),
            os.getenv("OLLAMA_MAX_TOKENS"),
            default="8192",
        ))
        return _chat_with_openai_models(
            self._client(),
            self.provider_label,
            self._models(),
            messages,
            temperature,
            max(max_tokens, configured_max_tokens),
        )


class AnthropicService(LLMService):
    def chat(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        return _chat_with_anthropic(self.config, messages, temperature, max_tokens)


class ClaudeCliService(LLMService):
    def chat(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        return _chat_with_claude_cli(self.config, messages, temperature, max_tokens)


def create_llm_service(config: dict) -> LLMService:
    provider = first_stripped(config.get("llm_provider"), default="openrouter").lower()
    services = {
        "openrouter": OpenRouterService,
        "nvidia": NvidiaService,
        "google": GoogleService,
        "zai": ZaiService,
        "z_ai": ZaiService,
        "ollama": OllamaService,
        "anthropic": AnthropicService,
        "claude_cli": ClaudeCliService,
    }
    try:
        return services[provider](config)
    except KeyError:
        supported = ", ".join(sorted(services))
        raise ValueError(f"Unsupported llm_provider '{provider}'. Supported: {supported}") from None


def _make_openrouter_client(config: dict) -> OpenAI:
    return OpenAI(
        api_key=first_stripped(config.get("openrouter_api_key"), os.getenv("OPENROUTER_API_KEY")),
        base_url="https://openrouter.ai/api/v1",
        timeout=_LLM_REQUEST_TIMEOUT,
    )


def _chat_with_anthropic(config: dict, messages: list[dict], temperature: float, max_tokens: int) -> str:
    try:
        import anthropic
    except ImportError:
        raise ImportError("Run: pip install 'autopilot-jobs[claude]'")
    api_key = first_stripped(config.get("anthropic_api_key"), os.getenv("ANTHROPIC_API_KEY"))
    model = first_stripped(config.get("anthropic_model"), default="claude-haiku-4-5-20251001")
    logger.debug(f"LLM call → Anthropic / {model}")
    t0 = time.time()
    client = anthropic.Anthropic(api_key=api_key, timeout=_LLM_REQUEST_TIMEOUT)
    system = next((m["content"] for m in messages if m["role"] == "system"), None)
    user_msgs = [m for m in messages if m["role"] != "system"]
    kwargs: dict = {
        "model": model,
        "messages": user_msgs,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system:
        kwargs["system"] = system
    r = client.messages.create(**kwargs)
    elapsed = time.time() - t0
    text = r.content[0].text
    logger.debug(f"LLM response: {len(text)} chars in {elapsed:.1f}s (input={r.usage.input_tokens} out={r.usage.output_tokens} tokens)")
    return text


def _chat_with_claude_cli(config: dict, messages: list[dict], temperature: float, max_tokens: int) -> str:
    model = first_stripped(config.get("claude_cli_model"))
    logger.debug(f"LLM call → Claude CLI{' / ' + model if model else ''}")
    t0 = time.time()

    system = next((m["content"] for m in messages if m["role"] == "system"), None)
    user_msgs = [m for m in messages if m["role"] != "system"]
    prompt_text = "\n\n".join(f"{m['role'].upper()}:\n{m['content']}" for m in user_msgs)

    # --strict-mcp-config suppresses all MCP servers in the subprocess; reduces ~27k context tokens
    cmd = [
        "claude", "--print", "--output-format", "json", "--tools", "",
        "--mcp-config", '{"mcpServers":{}}', "--strict-mcp-config",
        "--disable-slash-commands",
    ]
    if system:
        cmd += ["--system-prompt", system]
    if model:
        cmd += ["--model", model]

    try:
        result = subprocess.run(
            cmd,
            input=prompt_text,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "claude binary not found in PATH.\n"
            "Install Claude Code from https://claude.ai/code and run 'claude auth login'."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("claude CLI timed out after 300s.")

    if result.returncode != 0:
        raise RuntimeError(f"claude CLI exited {result.returncode}: {result.stderr.strip()}")

    try:
        data = json.loads(result.stdout)
        if isinstance(data, dict):
            text = data.get("result")
            if text is None:
                raise KeyError("no 'result' field in output")
        elif isinstance(data, list):
            result_event = next((e for e in data if isinstance(e, dict) and e.get("type") == "result"), None)
            if result_event is None:
                raise KeyError("no 'result' event found in output")
            text = result_event["result"]
        else:
            raise TypeError(f"unexpected output type: {type(data)}")
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
        raise RuntimeError(f"claude CLI unexpected output ({e}): {result.stdout[:200]}")

    elapsed = time.time() - t0
    logger.debug(f"LLM response: {len(text)} chars in {elapsed:.1f}s via claude CLI")
    return text


def chat_with_llm(
    config: dict,
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> str:
    return create_llm_service(config).chat(messages, temperature, max_tokens)


def _chat_with_openai_models(
    llm: OpenAI,
    provider_label: str,
    models: list[str],
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> str:
    if not models:
        raise RuntimeError(f"No models configured for {provider_label}.")

    for model_idx, model in enumerate(models):
        label = f"{provider_label} [model {model_idx + 1}/{len(models)}] {model}"
        requested_max_tokens = max_tokens
        for attempt in range(2):
            try:
                logger.debug(f"LLM call -> {label} (attempt {attempt + 1})")
                t0 = time.time()
                resp = llm.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=requested_max_tokens,
                )
                elapsed = time.time() - t0
                choice = resp.choices[0]
                text = choice.message.content or ""
                reasoning = getattr(choice.message, "reasoning", "") or ""
                finish_reason = getattr(choice, "finish_reason", "")
                if not text.strip() and reasoning and finish_reason == "length" and attempt == 0:
                    requested_max_tokens = min(
                        max(requested_max_tokens * 2, requested_max_tokens + 256),
                        8192,
                    )
                    logger.warning(
                        f"{label} used completion budget on reasoning before final content - "
                        f"retrying with max_tokens={requested_max_tokens}..."
                    )
                    continue
                if not text.strip() and reasoning:
                    raise RuntimeError(
                        f"{label} returned reasoning but no final content."
                    )
                usage = resp.usage
                if usage:
                    logger.debug(
                        f"LLM response: {len(text)} chars in {elapsed:.1f}s "
                        f"(in={usage.prompt_tokens} out={usage.completion_tokens} tokens) via {model}"
                    )
                else:
                    logger.debug(f"LLM response: {len(text)} chars in {elapsed:.1f}s via {model}")
                return text
            except RateLimitError:
                if attempt == 0:
                    logger.warning(f"Rate-limited on {model} - retrying in 3s...")
                    time.sleep(3)
                    continue
                logger.warning(f"Rate-limited on {model} (quota exhausted) - trying next model...")
                break
            except Exception as e:
                logger.exception(
                    f"LLM error ({model}) on attempt {attempt + 1}: "
                    f"{_format_exception_details(e)}"
                )
                break

    raise RuntimeError(
        f"All {provider_label} LLM models failed. Check prior logs for the exact transport/auth/provider error."
    )


def chat_with_fallback(
    llm: OpenAI,
    config: dict,
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> str:
    primary = first_stripped(config.get("openrouter_model"), OpenRouterService.default_model)
    fallbacks = config.get("openrouter_fallback_models") or []
    if isinstance(fallbacks, str):
        fallbacks = [m.strip() for m in fallbacks.split(",")]
    normalized_fallbacks = [first_stripped(m) for m in fallbacks]
    models = [primary] + [m for m in normalized_fallbacks if m and m != primary]
    return _chat_with_openai_models(
        llm,
        OpenRouterService.provider_label,
        models,
        messages,
        temperature,
        max_tokens,
    )
