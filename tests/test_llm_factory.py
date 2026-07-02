from autopilot_jobhunt.services.llm_factory import (
    GoogleAdkService,
    NvidiaAdkService,
    OllamaAdkService,
    create_llm_service,
)


def test_adk_factory_defaults_to_google():
    service = create_llm_service({})

    assert isinstance(service, GoogleAdkService)

def test_adk_factory_selects_nvidia():
    service = create_llm_service({"llm_provider": "nvidia"})

    assert isinstance(service, NvidiaAdkService)


def test_adk_factory_selects_ollama():
    service = create_llm_service({"llm_provider": "ollama"})

    assert isinstance(service, OllamaAdkService)


def test_ollama_service_uses_configured_base_url(monkeypatch):
    captured = {}

    class FakeLiteLlm:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        OllamaAdkService,
        "_load_litellm_class",
        lambda self: FakeLiteLlm,
    )

    service = OllamaAdkService(
        {
            "ollama_model": "llama3.1",
            "ollama_base_url": "http://localhost:11434/v1",
        }
    )
    service.create_model()

    assert captured["model"] == "openai/llama3.1"
    assert captured["api_key"] == "ollama"
    assert captured["api_base"] == "http://localhost:11434/v1"
