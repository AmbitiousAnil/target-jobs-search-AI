import json

from autopilot_jobhunt.config import loader, paths


def test_load_repo_config_reads_repo_root_config(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "config.json").write_text(
        json.dumps(
            {
                "llm_provider": " nvidia \n",
                "nvidia_fallback_models": [" google/gemma-4-31b-itb ", " meta/llama-3.1-8b-instruct\t"],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(loader, "get_repo_root", lambda: repo_root)

    assert loader.load_repo_config() == {
        "llm_provider": "nvidia",
        "nvidia_fallback_models": [
            "google/gemma-4-31b-itb",
            "meta/llama-3.1-8b-instruct",
        ],
    }


def test_load_repo_config_falls_back_to_example_file(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "config.example.json").write_text(
        json.dumps(
            {
                "llm_provider": " nvidia \n",
                "nvidia_model": " nvidia/nemotron-3-nano-30b-a3b ",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(loader, "get_repo_root", lambda: repo_root)

    assert loader.load_repo_config() == {
        "llm_provider": "nvidia",
        "nvidia_model": "nvidia/nemotron-3-nano-30b-a3b",
    }


def test_get_runtime_root_trims_env_override(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("JOBHUNT_ADK_RUNTIME_ROOT", f"  {runtime_root} \n")

    assert paths.get_runtime_root() == runtime_root.resolve()
