# Architecture Decisions

## ADR-001: Keep TinyFish-first job discovery and remove broad search

**Status:** Accepted

**Context:** The scanner originally combined company careers-page crawling, ATS listing expansion, and a broad TinyFish search query scoped to each company domain. The search query used hardcoded role terms, which could return stale postings, mirrored job-board pages, unrelated pages, or low-confidence URLs.

**Decision:** Job discovery should trust company-owned surfaces first. The scanner will fetch each configured `careers_url` with TinyFish, extract job-like links, detect ATS listing pages, and expand those ATS pages into individual job URLs. The broader search-query fallback is removed.

**Consequences:**

- Discovery is more precise and less likely to include stale or unrelated links.
- Scans depend more heavily on the quality of each `careers_url` and ATS detection.
- JavaScript-heavy career sites may still need a future rendered-browser fallback, but TinyFish remains the primary lightweight path.
- A browser tool such as Camofox may be added later only as fallback or visual confirmation, not as the default scan mechanism.

## ADR-002: Use an ATS-style resume match rubric for LLM scoring

**Status:** Accepted

**Context:** The original scoring prompt asked the LLM for a 0-100 fit score but only gave loose score bands. That made scores hard to explain because the model inferred its own weighting.

**Decision:** Job scoring now uses an explicit ATS-style resume-to-job rubric inspired by the `resume-ats-optimizer` workflow. The rubric evaluates title and seniority alignment, required years and ownership, technical keyword coverage, domain alignment, resume evidence quality, quantified impact, and location or remote fit. It also applies penalties for explicit `not_suitable` mismatches, missing required qualifications, and risky overclaims not evidenced in the resume.

**Consequences:**

- Scores are more explainable and consistent across jobs.
- The model is instructed not to inflate scores from generic profile text alone.
- The existing JSON output contract remains unchanged, so CSV export and drafting continue to work.
- `worth_applying` still follows the configured `candidate.min_score` threshold.

## ADR-003: Score one job description per LLM request and persist after each result

**Status:** Accepted

**Context:** The scanner originally batched up to 10 job descriptions plus the resume into one scoring prompt and expected one JSON array back. That worked poorly with local Ollama inference: large prompts were slow, single failures wasted an entire batch, and interrupted runs lost all partial progress because scan artifacts were only written at the end.

**Decision:** The scoring flow should use one resume plus one job description per LLM request, expect one JSON object back, and persist each scored job immediately after it returns. `last_scan.json`, `job_history.json`, and the CSV export are updated incrementally so already-scored jobs survive interruption.

**Consequences:**

- Ollama and other slower local models are less likely to time out because each request is smaller and isolated.
- Progress becomes observable and recoverable: if a run is stopped halfway through, completed scores are still available on disk.
- Low-score jobs are preserved with `worth_applying=false`, which makes the scan history more complete and auditable.
- Total scan wall-clock time may still be long, but failures are now localized to one JD instead of destroying a 10-job batch.

## ADR-004: Keep LLM provider selection behind a service factory

**Status:** Accepted

**Context:** The project supports multiple LLM backends including OpenRouter, Nvidia, Google, Z.ai, Ollama, Anthropic, and CLI-based providers. Scoring and drafting need one shared interface, but provider-specific concerns such as base URLs, retries, auth, and token limits vary significantly.

**Decision:** Provider selection remains centralized in the `create_llm_service(...)` factory and provider-specific behavior stays inside dedicated service classes. Callers such as the scanner and drafter continue to use `chat_with_llm(...)` without embedding provider conditionals in application logic.

**Consequences:**

- Scanner and drafter code stay focused on prompts and workflow instead of transport details.
- Provider-specific fixes, such as Ollama request sizing or OpenAI-compatible retry handling, can be changed in one place.
- Adding or removing providers remains low-risk because the public calling contract stays stable.
- Testing is simpler because workflow code can stub one chat entry point while factory and provider behavior are verified separately.

## ADR-005: Use one root ADK agent with direct tool orchestration

**Status:** Accepted

**Context:** The app workflow is mostly linear: configure the session, discover jobs, score them, tailor materials for a selected match, and export results. Earlier multi-agent handoff introduced extra prompt churn, more moving parts in traces, and avoidable ambiguity about which agent owned current session state.

**Decision:** The ADK app should use one root agent that directly orchestrates the workflow tools. Tool modules remain separate, but the runtime conversation stays under one stable master instruction with one short usage rule per tool. Session facts are read from tool outputs instead of being injected dynamically into the system prompt.

**Consequences:**

- Conversation flow is easier to trace because one agent owns the user interaction end to end.
- Prompt stability improves because there are no sub-agent transfers or dynamically rewritten instruction blocks.
- Tool implementations stay modular, so workflow logic can still evolve without reintroducing agent handoff complexity.
- This design is less suitable for highly parallel or deeply specialized domains, but it fits the current job-hunt workflow well.

## ADR-006: Use offline geographic normalization for location fit

**Status:** Accepted

**Context:** Job postings often mention only city names such as `Berlin`, `Bengaluru`, or `New York` instead of an explicit country token. Literal country-name matching can incorrectly reject otherwise relevant jobs and can also understate location fit during scoring.

**Decision:** Location matching should use offline geographic normalization, backed by packaged location data, to resolve city-to-country matches without external API calls. Preferred locations should also be included explicitly in the scoring context so the evaluator can award location-fit points from the same normalized inputs.

**Consequences:**

- City-only postings are less likely to be dropped before scoring.
- The location filter remains offline and deterministic, which keeps scans lightweight and deployable.
- Scoring becomes more faithful because preferred locations are visible both to the filter and to the evaluator prompt.
- Ambiguous city names can still produce edge cases, so the matcher remains heuristic rather than fully geocoded.

## ADR-007: Treat PDF as a first-class resume input and application output

**Status:** Accepted

**Context:** Users commonly start with a resume PDF rather than pasted plain text, and the main deliverables of the workflow are resume, cover-letter, and export documents that users expect to download directly. Supporting only text input and CSV-style output created avoidable friction in both local and deployed flows.

**Decision:** The application should treat PDF as a first-class format on both ends of the workflow. Configuration may accept an uploaded resume PDF and extract text centrally, while tailoring and export flows generate downloadable PDFs in addition to any existing markdown or CSV artifacts that remain useful internally.

**Consequences:**

- The workflow is smoother because users can start from the resume format they already have.
- Output artifacts are better aligned with the actual deliverables users want to submit or review.
- PDF extraction and rendering add dependency and formatting complexity that must be tested explicitly.
- Artifact handling becomes part of the core product path rather than an optional convenience layer.

## ADR-008: Make scoring results end with explicit job-selection handoff

**Status:** Accepted

**Context:** A completed scoring run is not useful if the user is left without a clear next step. When the workflow stopped after `score_and_rank_jobs`, the conversation could stall even though the data needed for tailoring was already available.

**Decision:** The scoring tool should return a ready-to-present ranked summary that includes total jobs scored, jobs above threshold, a compact top-match list, and explicit `job_ref` selection options for tailoring. The agent should present that summary directly and prompt the user to choose a job before moving into resume and cover-letter generation.

**Consequences:**

- The workflow becomes a guided sequence instead of a dead end after evaluation.
- Tailoring starts from stable `job_ref` identifiers instead of free-form user descriptions.
- Tool payloads become slightly richer, but the extra structure reduces prompt improvisation and ambiguity.
- Users still retain control over which job to pursue rather than being pushed automatically into the top-ranked result.

## ADR-009: Use the wrapped web app as the canonical runtime for downloadable artifacts

**Status:** Accepted

**Context:** Generated PDFs are only useful if the user can actually download them. The plain ADK web entrypoint does not expose the custom `/downloads/...` behavior needed by this repo, and deployed environments also need a reliable path from session artifacts to browser-downloadable files.

**Decision:** The canonical runtime for this project is the wrapped FastAPI app in `autopilot_jobhunt.web_app:app` when downloadable artifacts are required. Its download route should prefer normal artifact retrieval first and then fall back to session output files when needed, so generated PDFs remain reachable across local and deployed runs.

**Consequences:**

- Local and Cloud Run behavior are aligned around one runtime path for artifact downloads.
- Download links in tool responses can target a stable application-owned route instead of backend-specific storage details.
- The app remains dependent on session-local storage semantics until artifacts or session files move to external shared storage.
- Operational documentation must point users to the wrapped runtime, not the plain ADK web command, when PDF downloads matter.
