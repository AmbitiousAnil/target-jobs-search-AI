from __future__ import annotations

import json
import math

from ..discovery.location import build_candidate_profile
from ..llm.client import chat_with_llm


SCORE_PROMPT = """You are estimating an ATS-style resume-to-job match score for a candidate.
Output ONLY one JSON object, no other text.

CANDIDATE:
{candidate_profile}

RESUME SUMMARY:
{resume_summary}

JOB TO SCORE:
Company: {company}
Location: {location}
Title: {title}
URL: {url}
Content:
{job_text}

Score this single job against the candidate's resume and preferences using this 100-point rubric:
- Title and seniority alignment: 20 points
- Required years, ownership, and leadership match: 15 points
- Technical keyword coverage from the JD: 25 points
- Domain/problem alignment: 15 points
- Resume evidence quality and quantified impact: 15 points
- Location, remote policy, relocation, and stated preference fit: 10 points

Apply penalties after the rubric:
- Subtract up to 25 points for explicit mismatch with NOT suitable preferences.
- Subtract up to 15 points for major required qualifications missing from the resume.
- Subtract up to 10 points for risky overclaims where the JD requires experience that is not evidenced.

Do not inflate the score from generic profile text alone. Award points only when the resume
or candidate preferences provide support. If the job description is thin, score conservatively.

Output:
{{"score": 0-100, "title": "extracted job title", "stack": "key tech from JD", "location_remote": "location + remote policy", "reason": "fit summary", "worth_applying": true/false}}

Set worth_applying=true only if score >= {min_score}. Return exactly one object."""


def _coerce_score(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
    elif isinstance(value, str):
        try:
            numeric = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(numeric):
        return None
    return int(numeric)


def score_jobs(jobs: list[dict], resume: str, config: dict, on_job_started=None, on_scored_job=None) -> list[dict]:
    if not jobs:
        return []
    min_score = config.get("candidate", {}).get("min_score", 55)
    candidate_profile = build_candidate_profile(config)
    results: list[dict] = []
    for index, job in enumerate(jobs, start=1):
        if on_job_started:
            on_job_started(index, job.copy(), len(jobs))
        raw = chat_with_llm(
            config,
            messages=[{"role": "user", "content": SCORE_PROMPT.format(
                candidate_profile=candidate_profile,
                resume_summary=resume[:2500],
                company=job["company"],
                location=job["location"],
                title=job["title"],
                url=job["url"],
                job_text=job.get("content", job.get("snippet", ""))[:1500],
                min_score=min_score,
            )}],
            temperature=0.1,
        )
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end <= start:
            continue
        try:
            item = json.loads(raw[start:end])
        except json.JSONDecodeError:
            continue
        score = _coerce_score(item.get("score"))
        if score is None:
            continue
        scored_job = job.copy()
        scored_job.update(
            {
                "score": score,
                "extracted_title": item.get("title", job["title"]),
                "stack": item.get("stack", ""),
                "location_remote": item.get("location_remote", job["location"]),
                "reason": item.get("reason", ""),
                "worth_applying": item.get("worth_applying", False),
            }
        )
        results.append(scored_job)
        if on_scored_job:
            on_scored_job(scored_job.copy())
    return sorted(results, key=lambda item: item["score"], reverse=True)
