from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from tinyfish import TinyFish

from ..export.pdf import strip_markdown_code_fence, write_text_pdf
from ..llm.client import chat_with_llm


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _resolve_job(job_ref: str, *, last_scan_path: Path) -> tuple[str, str]:
    if job_ref.startswith("http"):
        return job_ref, "company"
    if not last_scan_path.exists():
        raise FileNotFoundError("No scan results found.")
    jobs = json.loads(last_scan_path.read_text(encoding="utf-8"))
    index = int(re.sub(r"\D", "", job_ref)) - 1
    if index < 0 or index >= len(jobs):
        raise ValueError(f"Job #{index + 1} not in last scan (found {len(jobs)} jobs)")
    job = jobs[index]
    return job["url"], _slug(job.get("company", "company"))


def _guidance_block(title: str, body: str | None) -> str:
    text = str(body or "").strip()
    return f"\n{title}:\n{text}\n" if text else ""


def draft_application(config: dict, job_ref: str, *, last_scan_path: Path, output_dir: Path, tailoring_guidance: dict[str, str] | None = None) -> Path:
    tf = TinyFish(api_key=config["tinyfish_api_key"])
    candidate = config.get("candidate", {})
    candidate_name = candidate.get("name", "the candidate")
    resume_path = Path(candidate.get("resume_path", "resume.md"))
    if not resume_path.is_absolute():
        resume_path = output_dir.parent / resume_path
    resume = resume_path.read_text(encoding="utf-8")
    job_url, company_slug = _resolve_job(job_ref, last_scan_path=last_scan_path)
    fetch_response = tf.fetch.get_contents([job_url], format="markdown")
    if not fetch_response.results or not fetch_response.results[0].text:
        raise RuntimeError(f"Failed to fetch JD. Errors: {fetch_response.errors}")
    jd_truncated = fetch_response.results[0].text[:4000]
    date_str = datetime.now().strftime("%Y-%m-%d")
    draft_output_dir = output_dir / f"{company_slug}-{date_str}"
    draft_output_dir.mkdir(parents=True, exist_ok=True)
    tailoring_guidance = tailoring_guidance or {}
    resume_guidance = _guidance_block("TAILORING SKILL GUIDANCE FOR RESUME REWRITES", tailoring_guidance.get("resume_guidance"))
    cover_guidance = _guidance_block("TAILORING SKILL GUIDANCE FOR COVER LETTERS", tailoring_guidance.get("cover_letter_guidance"))
    checklist_guidance = _guidance_block("APPLICATION OUTPUT CHECKLIST", tailoring_guidance.get("application_checklist"))

    resume_md = strip_markdown_code_fence(chat_with_llm(
        config,
        messages=[{"role": "user", "content": f"""Rewrite resume below to mirror language and emphasized skills in this job description.

Rules:
- Keep every fact truthful - do NOT invent experience
- Mirror JD terminology where candidate genuinely has that experience
- Reorder projects/bullets to surface most relevant experience first
- Keep same section structure
- Output full resume in Markdown
{resume_guidance}{checklist_guidance}

JOB DESCRIPTION:
{jd_truncated}

ORIGINAL RESUME:
{resume}

Output ONLY tailored resume in Markdown. No preamble."""}],
        temperature=0.2,
    ))
    resume_md_path = draft_output_dir / f"resume_{company_slug}.md"
    resume_md_path.write_text(resume_md, encoding="utf-8")
    write_text_pdf(resume_md, draft_output_dir / f"resume_{company_slug}.pdf", title=f"Tailored Resume - {candidate_name}", subtitle=f"Target job: {job_url}")

    cover_md = strip_markdown_code_fence(chat_with_llm(
        config,
        messages=[{"role": "user", "content": f"""Write one-page cover letter for {candidate_name} applying to this role.

Rules:
- Open with one specific reason this role fits {candidate_name}
- Paragraph 1: most relevant experience
- Paragraph 2: why this company specifically
- Close: clear ask for an interview
- Tone: direct and confident
- Do NOT use: "I am excited to apply", "I am a team player", "I am passionate about"
{cover_guidance}{checklist_guidance}

JOB DESCRIPTION:
{jd_truncated}

CANDIDATE RESUME:
{resume[:2500]}

Output ONLY cover letter. No preamble."""}],
        temperature=0.3,
    ))
    cover_md_path = draft_output_dir / f"cover_letter_{company_slug}.md"
    cover_md_path.write_text(cover_md, encoding="utf-8")
    write_text_pdf(cover_md, draft_output_dir / f"cover_letter_{company_slug}.pdf", title=f"Cover Letter - {candidate_name}", subtitle=f"Target job: {job_url}")

    info_txt = strip_markdown_code_fence(chat_with_llm(
        config,
        messages=[{"role": "user", "content": f"""Extract from this job posting:

1. Application URL or email
2. Hiring manager / recruiter name
3. Contact for questions info
4. Application deadline
5. Key requirements (max 8 bullets)
6. Nice-to-have skills (max 5 bullets)

JOB DESCRIPTION:
{jd_truncated}"""}],
        temperature=0.1,
    ))
    (draft_output_dir / "application_info.txt").write_text(f"Source URL: {job_url}\n\n{info_txt}", encoding="utf-8")
    return draft_output_dir
