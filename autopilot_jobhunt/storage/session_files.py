from __future__ import annotations

import json
import re
from dataclasses import asdict, replace
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from ..config.loader import load_repo_config
from ..config.paths import get_session_root
from ..domain.models import JobSearchConfiguration, StagedSession
from ..llm.factory import copy_provider_settings


def _dedupe_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in values:
        value = str(raw).strip()
        if value and value not in seen:
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
        raise ValueError(f"{field_label} must be full http/https URLs. Invalid values: " + ", ".join(invalid))
    return urls


def _normalize_string_list(values: list[str], field_name: str) -> list[str]:
    normalized = _dedupe_preserving_order(values)
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty.")
    return normalized


def validated_configuration(config: JobSearchConfiguration) -> JobSearchConfiguration:
    resume_text = config.resume_text.strip()
    if not resume_text:
        raise ValueError("Resume text cannot be empty.")
    return replace(
        config,
        resume_text=resume_text,
        company_urls=_validate_url_list(config.company_urls, "Company URLs"),
        target_roles=_normalize_string_list(config.target_roles, "target_roles"),
        target_locations=_normalize_string_list(config.target_locations, "target_locations"),
        min_score=max(0, min(100, int(config.min_score))),
        top_n=max(1, int(config.top_n)),
        llm_provider_override=(config.llm_provider_override or "").strip() or None,
    )


def _derive_company_name(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    parts = [part for part in host.split(".") if part and part not in {"com", "ai", "io", "co", "jobs"}]
    return parts[-1].replace("-", " ").title() if parts else (host or "Company")


def _derive_company_record(url: str, target_locations: list[str]) -> dict:
    return {
        "name": _derive_company_name(url),
        "careers_url": url,
        "search_domain": urlparse(url).netloc.lower(),
        "location": ", ".join(target_locations),
        "region": "Global",
    }


def stage_session_files(session_id: str, config: JobSearchConfiguration) -> StagedSession:
    validated = validated_configuration(config)
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
    companies_path.write_text(
        json.dumps([_derive_company_record(url, validated.target_locations) for url in validated.company_urls], indent=2),
        encoding="utf-8",
    )

    repo_config = load_repo_config()
    staged_config = {
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
    provider = validated.llm_provider_override or str(repo_config.get("llm_provider") or "").strip() or None
    if provider:
        staged_config["llm_provider"] = provider
        copy_provider_settings(provider=provider, source_config=repo_config, target_config=staged_config)
    config_path.write_text(json.dumps(staged_config, indent=2), encoding="utf-8")

    manifest_path.write_text(
        json.dumps(
            {
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
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return StagedSession(session_id, session_dir, resume_path, companies_path, config_path, manifest_path, state_dir, output_dir)


def load_manifest(session_dir: Path) -> dict:
    manifest_path = session_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest for session directory: {session_dir}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))

