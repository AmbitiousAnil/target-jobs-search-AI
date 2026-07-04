from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote


def artifact_inline_bytes(artifact: Any) -> bytes:
    inline_data = getattr(artifact, "inline_data", None)
    if inline_data is None or getattr(inline_data, "data", None) is None:
        raise RuntimeError("Uploaded artifact did not include inline PDF data.")
    return bytes(inline_data.data)


def _public_base_url() -> str | None:
    base_url = os.environ.get("ADK_PUBLIC_BASE_URL", "").strip()
    return base_url.rstrip("/") if base_url else None


def build_download_path(*, app_name: str, user_id: str, session_id: str, artifact_name: str, version: int | str) -> str:
    return (
        f"/downloads/{quote(app_name, safe='')}/{quote(user_id, safe='')}/"
        f"{quote(session_id, safe='')}/{quote(artifact_name, safe='')}"
        f"?version={quote(str(version), safe='')}"
    )


def build_download_url(download_path: str) -> str:
    base_url = _public_base_url()
    if not base_url:
        return download_path
    return f"{base_url}{download_path}"


def build_download_markdown(artifacts: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for artifact in artifacts:
        label = str(artifact.get("label") or artifact.get("filename") or "Download file").strip()
        url = str(artifact.get("download_url") or artifact.get("download_path") or "").strip()
        if url:
            lines.append(f"- [{label}]({url})")
    return "\n".join(lines)


def apply_download_labels(artifacts: list[dict[str, Any]], label_map: dict[str, str]) -> list[dict[str, Any]]:
    for artifact in artifacts:
        filename = str(artifact.get("filename") or artifact.get("label") or "").lower()
        for marker, label in label_map.items():
            if marker in filename:
                artifact["label"] = label
                break
    return artifacts


async def save_file_artifact(
    tool_context: Any | None,
    path: Path,
    *,
    artifact_name: str | None = None,
    mime_type: str | None = None,
    custom_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if tool_context is None or not hasattr(tool_context, "save_artifact"):
        return None

    try:
        from google.genai import types
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Google GenAI types are unavailable for artifact export.") from exc

    filename = artifact_name or path.name
    resolved_mime_type = mime_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    version = await tool_context.save_artifact(
        filename,
        types.Part(
            inline_data=types.Blob(
                data=path.read_bytes(),
                mime_type=resolved_mime_type,
                display_name=filename,
            )
        ),
        custom_metadata=custom_metadata or {"source_path": str(path)},
    )
    session = getattr(tool_context, "session", None)
    app_name = getattr(session, "app_name", None)
    user_id = getattr(tool_context, "user_id", None) or getattr(session, "user_id", None)
    session_id = getattr(session, "id", None)
    download_path = None
    download_url = None
    if app_name and user_id and session_id:
        download_path = build_download_path(
            app_name=str(app_name),
            user_id=str(user_id),
            session_id=str(session_id),
            artifact_name=filename,
            version=version,
        )
        download_url = build_download_url(download_path)
    return {
        "label": filename,
        "filename": filename,
        "version": version,
        "mime_type": resolved_mime_type,
        "download_ready": True,
        "download_path": download_path,
        "download_url": download_url,
    }

