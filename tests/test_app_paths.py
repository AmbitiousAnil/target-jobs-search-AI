import json

from autopilot_jobhunt import app_paths


def test_load_repo_config_reads_repo_root_config(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config_path = repo_root / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "llm_provider": " nvidia \n",
                "nvidia_fallback_models": [" google/gemma-4-31b-itb ", " meta/llama-3.1-8b-instruct\t"],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(app_paths, "get_pilot_root", lambda: repo_root)

    assert app_paths.get_repo_root() == repo_root
    assert app_paths.load_repo_config() == {
        "llm_provider": "nvidia",
        "nvidia_fallback_models": [
            "google/gemma-4-31b-itb",
            "meta/llama-3.1-8b-instruct",
        ],
    }


def test_load_repo_config_falls_back_to_example_file(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config_path = repo_root / "config.example.json"
    config_path.write_text(
        json.dumps(
            {
                "llm_provider": " nvidia \n",
                "nvidia_model": " nvidia/nemotron-3-nano-30b-a3b ",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(app_paths, "get_pilot_root", lambda: repo_root)

    assert app_paths.load_repo_config() == {
        "llm_provider": "nvidia",
        "nvidia_model": "nvidia/nemotron-3-nano-30b-a3b",
    }


def test_get_runtime_root_trims_env_override(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("JOBHUNT_ADK_RUNTIME_ROOT", f"  {runtime_root} \n")

    assert app_paths.get_runtime_root() == runtime_root.resolve()
