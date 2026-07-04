import asyncio
import base64

from autopilot_jobhunt.export import artifacts as artifact_utils
from autopilot_jobhunt.export import pdf as pdf_utils
from autopilot_jobhunt import web_app


class FakeSession:
    def __init__(self):
        self.id = "session-7"
        self.user_id = "user"
        self.app_name = "autopilot_jobhunt"


class FakeToolContext:
    def __init__(self):
        self.session = FakeSession()
        self.user_id = self.session.user_id

    async def save_artifact(self, filename, artifact, custom_metadata=None):
        return 3


def test_save_file_artifact_builds_download_urls(tmp_path, monkeypatch):
    monkeypatch.delenv("ADK_PUBLIC_BASE_URL", raising=False)
    file_path = tmp_path / "resume.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")

    artifact = asyncio.run(artifact_utils.save_file_artifact(FakeToolContext(), file_path))

    assert artifact is not None
    assert artifact["filename"] == "resume.pdf"
    assert artifact["download_path"] == "/downloads/autopilot_jobhunt/user/session-7/resume.pdf?version=3"
    assert artifact["download_url"] == artifact["download_path"]


def test_save_file_artifact_uses_public_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("ADK_PUBLIC_BASE_URL", "https://jobhunt.example.run.app/")
    file_path = tmp_path / "cover_letter.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")

    artifact = asyncio.run(artifact_utils.save_file_artifact(FakeToolContext(), file_path))

    assert artifact is not None
    assert artifact["download_url"] == (
        "https://jobhunt.example.run.app/downloads/"
        "autopilot_jobhunt/user/session-7/cover_letter.pdf?version=3"
    )


def test_build_download_markdown():
    artifacts = [
        {
            "label": "Tailored Resume PDF",
            "filename": "resume_company.pdf",
            "version": 0,
            "mime_type": "application/pdf",
            "download_path": "/downloads/autopilot_jobhunt/user/session-7/resume_company.pdf?version=0",
            "download_url": "/downloads/autopilot_jobhunt/user/session-7/resume_company.pdf?version=0",
        },
        {
            "label": "Tailored Cover Letter PDF",
            "filename": "cover_letter_company.pdf",
            "version": 1,
            "mime_type": "application/pdf",
            "download_path": "/downloads/autopilot_jobhunt/user/session-7/cover_letter_company.pdf?version=1",
            "download_url": "/downloads/autopilot_jobhunt/user/session-7/cover_letter_company.pdf?version=1",
        },
    ]

    markdown = artifact_utils.build_download_markdown(artifacts)
    assert "[Tailored Resume PDF](/downloads/autopilot_jobhunt/user/session-7/resume_company.pdf?version=0)" in markdown
    assert "[Tailored Cover Letter PDF](/downloads/autopilot_jobhunt/user/session-7/cover_letter_company.pdf?version=1)" in markdown


def test_download_payload_decoder_uses_urlsafe_base64():
    original = b"%PDF-1.4\nhello world"
    payload = {
        "inlineData": {
            "data": base64.urlsafe_b64encode(original).decode("ascii").rstrip("="),
            "mimeType": "application/pdf",
            "displayName": "resume.pdf",
        }
    }

    binary, mime_type, display_name = web_app._decode_artifact_payload(payload, "resume.pdf")

    assert binary == original
    assert mime_type == "application/pdf"
    assert display_name == "resume.pdf"


def test_normalize_text_strips_markdown_code_fence():
    assert pdf_utils._normalize_text("```markdown\n# Header\nLine\n```") == "# Header\nLine"
