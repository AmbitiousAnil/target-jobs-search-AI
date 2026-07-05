# AGENTS.md

## Local ADK Run Note

Use wrapped web app when you need working PDF download links in repo.

- Repo root: `D:\My_Projects\adk-jobhunt-pilot`
- Direct agent folder: `D:\My_Projects\adk-jobhunt-pilot\autopilot_jobhunt`
- Start from repo root
- Use venv Python module entrypoint, not `.venv\Scripts\adk.exe`

Working command for chat plus `/downloads/...` links:

```powershell
.\.venv\Scripts\python.exe -m uvicorn autopilot_jobhunt.web_app:app --host 127.0.0.1 --port 8080
```

Plain ADK UI only, without custom download routes:

```powershell
.\.venv\Scripts\python.exe -m google.adk.cli web --host 127.0.0.1 --port 8080 autopilot_jobhunt
```

Current default provider:

- committed default lives in `config.example.json` and sets `llm_provider` to `nvidia`
- local `config.json` is for machine-specific overrides and should stay out of git
- ADK model creation and session tool flows read provider settings from `autopilot_jobhunt/llm/` and `autopilot_jobhunt/config/`

Why this path:

- `autopilot_jobhunt/agent.py` contains ADK `root_agent`
- `.venv\Scripts\adk.exe` exited silently in this environment, while Python module entrypoint worked
- `autopilot_jobhunt/web_app.py` adds `/downloads/...` endpoints that resume and cover-letter PDF links use
