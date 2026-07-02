# AGENTS.md

## Local ADK Run Note

Use this exact startup path for the ADK web UI in this repo.

- Repo root: `D:\My_Projects\adk-jobhunt-pilot`
- Direct agent folder: `D:\My_Projects\adk-jobhunt-pilot\autopilot_jobhunt`
- Start from repo root, but point ADK at `autopilot_jobhunt`
- Use the venv Python module entrypoint, not `.venv\Scripts\adk.exe`

Working command:

```powershell
.\.venv\Scripts\python.exe -m google.adk.cli web --host 127.0.0.1 --port 8080 autopilot_jobhunt
```

Current default provider:

- committed default lives in `config.example.json` and sets `llm_provider` to `nvidia`
- local `config.json` is for machine-specific overrides and should stay out of git
- ADK model creation and session tool flows read provider settings from the factory/registry under `autopilot_jobhunt/services/`

Why this path:

- `autopilot_jobhunt\agent.py` contains the ADK `root_agent`
- `.venv\Scripts\adk.exe` exited silently in this environment, while the Python module entrypoint worked
