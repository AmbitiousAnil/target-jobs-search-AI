from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RAW_JOBS_FILE_NAME = "raw_jobs.json"
LAST_SCAN_FILE_NAME = "last_scan.json"
JOB_HISTORY_FILE_NAME = "job_history.json"
SCAN_STATUS_FILE_NAME = "scan_status.json"


def raw_jobs_path(state_dir: Path) -> Path:
    return state_dir / RAW_JOBS_FILE_NAME


def last_scan_path(state_dir: Path) -> Path:
    return state_dir / LAST_SCAN_FILE_NAME


def job_history_path(state_dir: Path) -> Path:
    return state_dir / JOB_HISTORY_FILE_NAME


def scan_status_path(state_dir: Path) -> Path:
    return state_dir / SCAN_STATUS_FILE_NAME


def read_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def read_json_dict(path: Path) -> dict | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_raw_jobs(state_dir: Path) -> list[dict]:
    return read_json_list(raw_jobs_path(state_dir))


def read_last_scan(state_dir: Path) -> list[dict]:
    return read_json_list(last_scan_path(state_dir))


def read_job_history(state_dir: Path) -> list[dict]:
    return read_json_list(job_history_path(state_dir))


def read_scan_status(state_dir: Path) -> dict | None:
    return read_json_dict(scan_status_path(state_dir))


def write_scan_status(state_dir: Path, payload: dict[str, Any]) -> Path:
    path = scan_status_path(state_dir)
    payload_to_write = payload.copy()
    payload_to_write["last_updated"] = datetime.now(timezone.utc).isoformat()
    write_json(path, payload_to_write)
    return path


def latest_matching_file(output_dir: Path, pattern: str) -> str | None:
    matches = sorted(output_dir.glob(pattern), key=lambda path: path.stat().st_mtime) if output_dir.exists() else []
    return str(matches[-1]) if matches else None


def latest_output_subdir(output_dir: Path) -> str | None:
    matches = sorted([path for path in output_dir.iterdir() if path.is_dir()], key=lambda path: path.stat().st_mtime) if output_dir.exists() else []
    return str(matches[-1]) if matches else None

