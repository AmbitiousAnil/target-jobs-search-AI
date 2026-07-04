from autopilot_jobhunt.config.text import sanitize_nested_strings
from autopilot_jobhunt.llm.providers.openai_compatible import OpenRouterService, NvidiaService, create_chat_service


def test_sanitize_nested_strings_trims_recursive_config_values():
    payload = {
        "llm_provider": " nvidia \n",
        "candidate": {
            "name": "  Anil  ",
            "countries": [" India ", "\tRemote\t"],
        },
    }

    assert sanitize_nested_strings(payload) == {
        "llm_provider": "nvidia",
        "candidate": {
            "name": "Anil",
            "countries": ["India", "Remote"],
        },
    }


def test_llm_service_trims_provider_and_api_key_values():
    service = create_chat_service({"llm_provider": " nvidia \r\n"})

    assert isinstance(service, NvidiaService)
    assert OpenRouterService({"openrouter_api_key": " sk-test \r\n"})._api_key() == "sk-test"
