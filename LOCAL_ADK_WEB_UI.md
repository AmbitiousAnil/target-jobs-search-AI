# Local ADK Web UI

## Install

```bash
cd adk-jobhunt-pilot
python -m venv .venv
.venv\Scripts\activate
pip install -e .[adk,dev]
```

## Environment Variables

Set the provider keys outside chat:

```bash
set TINYFISH_API_KEY=...
set OPENROUTER_API_KEY=...
set GOOGLE_API_KEY=...
```

Optional overrides:

```bash
set ADK_MODEL=gemini-2.5-flash
set JOB_HUNT_SOURCE_ROOT=D:\My_Projects\autopilot-jobhunt
```

`JOB_HUNT_SOURCE_ROOT` matters when this folder is moved away from the repo and the `job_hunt` package is no longer importable from a sibling path.

## Start The UI

```bash
adk web .
```

Useful variants:

```bash
adk web --host 0.0.0.0 --port 8000 .
adk web --session_service_uri "sqlite:///runtime/adk_sessions.db" .
```

## Suggested Demo Flow

1. Paste resume text.
2. Provide one or more company career URLs.
3. Provide target roles and target locations.
4. Let the agent call `configure_job_search(...)`.
5. Ask it to scan.
6. Ask it to draft for `#1` or another result.
7. Ask it to export results.

## Runtime Artifacts

Each session writes only inside:

```text
runtime/sessions/<session_id>/
```

That directory contains the staged `config.json`, `companies.json`, `resume.md`, `state/`, and `output/` files for the current session.
