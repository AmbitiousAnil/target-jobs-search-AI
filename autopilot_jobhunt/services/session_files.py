from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from ..app_paths import get_session_root, load_repo_config
from .llm_factory import copy_provider_settings


def _load_repo_config() -> dict:
    return load_repo_config()


def resolve_tinyfish_api_key() -> str:
    repo_config = _load_repo_config()
    config_key = str(repo_config.get("tinyfish_api_key") or "").strip()
    if config_key:
        return config_key

    env_key = str(os.getenv("TINYFISH_API_KEY") or "").strip()
    return env_key


def _dedupe_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in values:
        value = str(raw).strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "session"


def _validate_url_list(urls: list[str], field_label: str) -> list[str]:
    urls = _dedupe_preserving_order(urls)
    invalid = []
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            invalid.append(url)

    if invalid:
        raise ValueError(
            f"{field_label} must be full http/https URLs. Invalid values: "
            + ", ".join(invalid)
        )

    return urls


def _normalize_string_list(values: list[str], field_name: str) -> list[str]:
    normalized = _dedupe_preserving_order(values)
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty.")
    return normalized


def _derive_company_name(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    parts = [part for part in host.split(".") if part and part not in {"com", "ai", "io", "co", "jobs"}]
    if not parts:
        return host or "Company"
    return parts[-1].replace("-", " ").title()


def _derive_company_record(url: str, target_locations: list[str]) -> dict:
    return {
        "name": _derive_company_name(url),
        "careers_url": url,
        "search_domain": urlparse(url).netloc.lower(),
        "location": ", ".join(target_locations),
        "region": "Global",
    }


@dataclass(frozen=True)
class JobSearchConfiguration:
    resume_text: str
    company_urls: list[str]
    target_roles: list[str]
    target_locations: list[str]
    min_score: int = 60
    top_n: int = 5
    llm_provider_override: str | None = None

    def validated(self) -> "JobSearchConfiguration":
        resume_text = self.resume_text.strip()
        if not resume_text:
            raise ValueError("Resume text cannot be empty.")

        min_score = max(0, min(100, int(self.min_score)))
        top_n = max(1, int(self.top_n))

        llm_provider = self.llm_provider_override.strip() if self.llm_provider_override else None
        company_urls = _validate_url_list(self.company_urls, "Company URLs")
        if not company_urls:
            raise ValueError("At least one company URL is required.")

        return JobSearchConfiguration(
            resume_text=resume_text,
            company_urls=company_urls,
            target_roles=_normalize_string_list(self.target_roles, "target_roles"),
            target_locations=_normalize_string_list(self.target_locations, "target_locations"),
            min_score=min_score,
            top_n=top_n,
            llm_provider_override=llm_provider or None,
        )

    def public_summary(self) -> dict:
        return {
            "company_urls": list(self.company_urls),
            "target_roles": list(self.target_roles),
            "target_locations": list(self.target_locations),
            "min_score": self.min_score,
            "top_n": self.top_n,
            "llm_provider_override": self.llm_provider_override,
            "resume_chars": len(self.resume_text),
        }


@dataclass(frozen=True)
class StagedSession:
    session_id: str
    session_dir: Path
    resume_path: Path
    companies_path: Path
    config_path: Path
    manifest_path: Path
    state_dir: Path
    output_dir: Path


def _apply_llm_provider_settings(staged_config: dict, validated: JobSearchConfiguration) -> None:
    repo_config = _load_repo_config()
    provider = (
        validated.llm_provider_override
        or str(repo_config.get("llm_provider") or "").strip()
        or None
    )
    if not provider:
        return

    staged_config["llm_provider"] = provider
    copy_provider_settings(
        provider=provider,
        source_config=repo_config,
        target_config=staged_config,
    )


def stage_session_files(session_id: str, config: JobSearchConfiguration) -> StagedSession:
    validated = config.validated()

    safe_session_id = _slugify(session_id)
    session_dir = get_session_root() / safe_session_id
    state_dir = session_dir / "state"
    output_dir = session_dir / "output"

    session_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    resume_path = session_dir / "resume.md"
    companies_path = session_dir / "companies.json"
    config_path = session_dir / "config.json"
    manifest_path = session_dir / "manifest.json"

    resume_path.write_text(validated.resume_text, encoding="utf-8")

    company_records = [
        _derive_company_record(url, validated.target_locations)
        for url in validated.company_urls
    ]
    companies_path.write_text(json.dumps(company_records, indent=2), encoding="utf-8")

    staged_config = {
        # Keep secrets runtime-only. The ADK layer injects provider keys when it
        # executes scout/evaluator/tailoring work for this session.
        "tinyfish_api_key": "",
        "candidate": {
            "name": "ADK Session Candidate",
            "resume_path": "resume.md",
            "min_score": validated.min_score,
            "top_n": validated.top_n,
            "countries": validated.target_locations,
            "target_roles": validated.target_roles,
            "target_locations": validated.target_locations,
        },
        "adk_session": {
            "company_urls": validated.company_urls,
            "target_roles": validated.target_roles,
            "target_locations": validated.target_locations,
        },
    }
    _apply_llm_provider_settings(staged_config, validated)

    config_path.write_text(json.dumps(staged_config, indent=2), encoding="utf-8")

    manifest = {
        "session_id": session_id,
        "safe_session_id": safe_session_id,
        "configuration": asdict(validated),
        "files": {
            "resume_path": str(resume_path),
            "companies_path": str(companies_path),
            "config_path": str(config_path),
            "state_dir": str(state_dir),
            "output_dir": str(output_dir),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return StagedSession(
        session_id=session_id,
        session_dir=session_dir,
        resume_path=resume_path,
        companies_path=companies_path,
        config_path=config_path,
        manifest_path=manifest_path,
        state_dir=state_dir,
        output_dir=output_dir,
    )


def load_manifest(session_dir: Path) -> dict:
    manifest_path = session_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest for session directory: {session_dir}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))
