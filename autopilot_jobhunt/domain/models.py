from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JobSearchConfiguration:
    resume_text: str
    company_urls: list[str]
    target_roles: list[str]
    target_locations: list[str]
    min_score: int = 60
    top_n: int = 5
    llm_provider_override: str | None = None

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

