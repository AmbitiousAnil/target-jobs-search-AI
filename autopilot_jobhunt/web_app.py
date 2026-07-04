from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from google.adk.cli.fast_api import get_fast_api_app


_INTERNAL_BASE_URL = "http://adk.local"


def _agents_dir() -> str:
    return str(Path(__file__).resolve().parent)


def _port() -> int:
    try:
        return int(os.environ.get("PORT", "8080"))
    except ValueError:
        return 8080


def _artifact_api_path(
    *,
    app_name: str,
    user_id: str,
    session_id: str,
    artifact_name: str,
    version: str,
) -> str:
    return (
        f"/apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/"
        f"{artifact_name}/versions/{version}"
    )


async def _internal_get_json(request: Request, path: str) -> dict | list:
    transport = httpx.ASGITransport(app=request.app)
    async with httpx.AsyncClient(transport=transport, base_url=_INTERNAL_BASE_URL) as client:
        response = await client.get(path)
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if response.is_error:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


def _decode_artifact_payload(payload: dict, artifact_name: str) -> tuple[bytes, str, str]:
    inline_data = payload.get("inlineData") or payload.get("inline_data") or {}
    encoded_bytes = inline_data.get("data")
    if not encoded_bytes:
        raise HTTPException(status_code=500, detail="Artifact payload did not include inline file bytes.")

    try:
        binary = base64.urlsafe_b64decode(f"{encoded_bytes}{'=' * (-len(encoded_bytes) % 4)}")
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Artifact payload could not be decoded.") from exc

    mime_type = (
        inline_data.get("mimeType")
        or inline_data.get("mime_type")
        or "application/octet-stream"
    )
    display_name = (
        inline_data.get("displayName")
        or inline_data.get("display_name")
        or artifact_name
    )
    return binary, str(mime_type), str(display_name)


def create_app() -> FastAPI:
    app = get_fast_api_app(
        agents_dir=_agents_dir(),
        web=True,
        host="0.0.0.0",
        port=_port(),
    )

    @app.get(
        "/downloads/{app_name}/{user_id}/{session_id}/{artifact_name:path}",
        response_class=Response,
    )
    async def download_artifact(
        request: Request,
        app_name: str,
        user_id: str,
        session_id: str,
        artifact_name: str,
        version: str = Query("latest"),
    ) -> Response:
        payload = await _internal_get_json(
            request,
            _artifact_api_path(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                artifact_name=artifact_name,
                version=version,
            ),
        )
        if not isinstance(payload, dict):
            raise HTTPException(status_code=500, detail="Unexpected artifact payload.")

        binary, mime_type, display_name = _decode_artifact_payload(payload, artifact_name)
        headers = {"Content-Disposition": f'attachment; filename="{display_name}"'}
        return Response(content=binary, media_type=mime_type, headers=headers)

    return app


app = create_app()
