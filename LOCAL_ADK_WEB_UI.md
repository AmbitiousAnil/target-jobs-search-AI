# Local ADK Web UI

## Install

```powershell
python -m venv .venv
.\.venv\Scriptsctivate
pip install -e .[dev]
```

## Environment Variables

Set provider keys outside chat:

```powershell
set TINYFISH_API_KEY=...
set GOOGLE_API_KEY=...
set NVIDIA_API_KEY=...
```

## Start UI

```powershell
.\.venv\Scripts\python.exe -m google.adk.cli web --host 127.0.0.1 --port 8080 autopilot_jobhunt
```

Wrapped UI with download routes:

```powershell
.\.venv\Scripts\python.exe -m uvicorn autopilot_jobhunt.web_app:app --host 127.0.0.1 --port 8080
```

## Suggested Demo Flow

1. Paste resume text or upload resume PDF.
2. Provide company career URLs.
3. Provide target roles and target locations.
4. Let agent call `configure_candidate_search(...)`.
5. Ask it to scan.
6. Ask it to score and rank.
7. Ask it to tailor selected `job_ref`.
8. Ask it to export results.
