---
name: job-application-tailor
description: Tailor resume and cover-letter outputs for a selected job using truthful resume rewriting, JD language alignment, and recruiter-friendly packaging. Use when Codex or an agent needs to generate application materials for one chosen role after job discovery and ranking are complete.
---

# Job Application Tailor

Use this skill after a specific job has been selected.

## Workflow

1. Read the chosen job description and identify the core requirements, domain cues, and vocabulary.
2. Rewrite the resume to surface relevant evidence first without inventing experience.
3. Draft a concise cover letter that explains fit for the role and company using concrete details.
4. Check the outputs against the application checklist before returning or saving them.

## Resume Rewrite Rules

- Mirror job-description terminology only when the candidate truly has that experience.
- Reorder bullets and projects to foreground the strongest matching evidence.
- Keep the original resume's core structure unless a small adjustment improves relevance.
- Prefer quantified impact, scope, tools, and ownership over generic claims.
- Never add missing experience, years, credentials, or leadership that the source resume does not support.

Read `references/resume-tailoring.md` when generating or reviewing the tailored resume.

## Cover Letter Rules

- Open with a specific fit statement grounded in the job description.
- Keep the body focused on relevant evidence and company-specific motivation.
- End with a direct closing and interview ask.
- Avoid generic enthusiasm filler and empty soft-skill claims.

Read `references/cover-letter-tailoring.md` when generating or reviewing the cover letter.

## Output Check

Use `assets/application-output-checklist.md` as the final pass before saving the deliverables.
