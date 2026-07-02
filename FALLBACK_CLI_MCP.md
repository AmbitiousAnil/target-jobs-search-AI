# Fallback CLI And MCP Path

If ADK or Cloud Run is unavailable, the original project flow remains unchanged.

## CLI

From the existing repo root:

```bash
autopilot scan
autopilot draft 1
autopilot export --min 70
```

## MCP Server

From the existing repo root:

```bash
python -m job_hunt.mcp_server
```

## Why This Backup Path Still Works

- This pilot does not edit the existing `job_hunt` package.
- It does not modify the root `pyproject.toml`.
- It does not modify the current CLI or MCP entrypoints.
- All ADK-specific files live only inside `adk-jobhunt-pilot/`.
