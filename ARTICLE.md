# Building Autopilot Jobhunt: A Job-Hunting Agent I Actually Wanted to Use

*How I turned a messy weekend script into a single conversational agent that scouts real career pages, scores every role against your resume, and rewrites your application without lying on it.*

---

## Let's be honest: job hunting is exhausting

If you've done a real job search recently, you know the loop. You open a dozen company career pages. You skim a hundred listings trying to guess which ones actually fit. You paste a job description into a doc, then burn forty minutes reshuffling resume bullets and rewriting your cover letter so it sounds like you read the posting. Then you do the whole thing again for the next role. And the next.

The annoying part isn't any single step. It's that the whole thing is repetitive, scattered, and impossible to personalize when you're applying to more than two or three places. Your preferences live in your head and have to be re-typed every time. And the tailoring part, which is the part that actually matters, is where most people either rush or quietly pad their resume with stuff they can't back up in the interview.

I wanted a tool that could take me from *"here's my resume and the five companies I care about"* to *"here are tailored, downloadable materials for the one role you picked"*, while I steered it in plain English and while it stayed honest.

So I built one. It's called **Autopilot Jobhunt**, and it runs on the **Google Agent Development Kit (ADK)**.

In this post, I'll share:

- **The "Why":** the problem I wanted to solve (based on my own job prep).
- **The "What":** what the agent actually does.
- **The "How":** the tools I used (ADK, TinyFish, LiteLLM, and friends) and why I picked them.
- **Behind the Scenes:** some key moments, challenges, and code snippets from the build.
- **What's Next:** where I see this project going.

---

## The "Why": the problem I wanted to solve

I didn't set out to build an "AI product." I set out to stop doing four things that were driving me up the wall during my own search:

1. **Restating context.** My target roles, locations, and my "I won't go below this" bar had to be re-supplied to every search I ran.
2. **Not trusting the black box.** Most job-scraper scripts smash discovery, filtering, and scoring into one blob you can't inspect. You never know if it was thorough or just busy.
3. **Slow, sloppy tailoring.** Customizing a resume and cover letter per role is the highest-value step and the one I rushed the most, usually right into keyword-stuffing I'd regret.
4. **Scale.** Doing all of that across several companies is just hours of browsing and copy-paste.

The interesting problem here was never *fetching* jobs. Anyone can scrape a page. The interesting problem was making a ranked, tailored pipeline that stays **truthful** and that I could actually steer and trust.

And here's the question the whole thing kept coming back to: why an agent at all? Why not just a script?

Because the workflow is a bunch of *decisions*, not a fixed batch job. Should I re-scan these career pages or reuse what I found five minutes ago? Which of these thirty jobs are even worth scoring? Which single role do I want to tailor for? What do I export, and in what format? Those are judgment calls, and that's exactly what an agent is good at. A single ADK agent owns the conversation and picks the next tool to call, so I drive in plain English while it keeps the steps in the right order. Every step is a tool call I can read in the logs, not hidden state mutating somewhere.

One thing I'll defend: this is *one* agent orchestrating its tools, not a swarm of specialist sub-agents handing off to each other. I tried the multi-agent version first. It was more impressive on a diagram and worse in practice. More prompt churn, more noise in every trace, and constant confusion about which agent "owned" the session right now. For a mostly linear flow like configure → discover → score → tailor → export, one agent that just calls its tools is easier to explain, easier to test, and way easier to demo. Every capability maps to exactly one tool.

---

## The "What": what the agent actually does

Autopilot Jobhunt gives you six things, and the agent calls them roughly in this order:

1. **Configure** — Stage your inputs: resume (pasted text *or* an uploaded PDF), company career URLs, target roles, target locations, a minimum fit score, and how many top matches to keep.
2. **Scout** — Discover live job postings straight from the company career pages you gave it. Real pages, not a stale dataset.
3. **Score & rank** — Score every discovered job against your resume with an explicit rubric, then rank them.
4. **Tailor** — For the one role you pick, generate a tailored resume *and* cover letter, in both Markdown and downloadable PDF.
5. **Export** — Dump the scored results to PDF or CSV with clickable download links.
6. **Inspect** — Two read-only tools so you can always ask "what have you got staged?" and "where are we in the process?"

Discovered jobs and scores are cached per session, so re-running a scan or score reuses what it already has unless your configuration actually changed. You don't pay for the same scrape twice.

The flow, start to finish:

```
configure_candidate_search
        │
scan_company_jobs
        │
score_and_rank_jobs
        ├── tailor_application_materials   (for the one job you pick)
        └── export_results                 (PDF or CSV, with download links)
```

---

## The "How": the tools I used and why

Here's what I reached for, and the honest reason for each.

**Google ADK (`google-adk`)** was the backbone. It gave me the agent runtime, the app container, tool calling, an artifact service for generated files, and a built-in web UI. I wrapped that UI in a thin FastAPI app to add my own download routes, which I'll get to.

**TinyFish** handled live web-fetching. Instead of scraping some static job-board dump, it lets the agent fetch and extract job data from real company career pages at runtime, with rate-limit-aware batching. Deciding to trust company-owned pages first, rather than firing off a broad search query, was one of my better calls. It kept discovery clean and cut out the mirrored, months-old job-board copies that a search would've dragged in.

**LiteLLM plus a little provider factory** meant I didn't have to marry one LLM vendor. One registry feeds two different things: the ADK agent's model, and a plain text-completion client I use for scoring and drafting. NVIDIA, Google, OpenRouter, Z.ai, and local Ollama are all swappable from config or an environment variable, each with its own fallback model chain.

**reportlab and pypdf** are the unglamorous but essential bit. They render tailored resumes, cover letters, and export tables into actual PDFs, and pull text back *out* of an uploaded resume PDF. PDF is a first-class thing on both ends, because that's the format people actually have and actually want back.

**Agent Skills** turned out to be the most important lever of all, and it's where the "honest" promise gets enforced. More on that below.

---

## Behind the Scenes: challenges and code

### One agent, seven tools, one instruction

The core is genuinely small. The root agent is just a model, a description, a master instruction, and its list of tools:

```python
root_agent = Agent(
    name=APP_NAME,
    model=_build_adk_model(),
    description=(
        "Session-aware single-agent job-hunt assistant that coordinates "
        "configuration, job discovery, scoring, tailoring, and export "
        "through explicit tool handoffs."
    ),
    instruction=MASTER_INSTRUCTION,
    tools=[
        configure_candidate_search,
        scan_company_jobs,
        score_and_rank_jobs,
        tailor_application_materials,
        export_results,
        show_current_configuration,
        show_scan_status,
    ],
)
```

The rule I forced on myself: tools stay thin. A tool reads the ADK context, calls exactly one service, and formats the reply. No business logic in the tool layer. The real orchestration lives in a `services/` layer, and the focused capabilities (discovery, scoring, tailoring, export, storage) sit below that. The dependency direction only ever points downward, and I wired up import-linter in CI to *enforce* that, so the agent layer can't quietly reach into a low-level module and tangle everything back up:

```
agent / tools  →  services  →  { discovery, scoring, tailoring, export, storage, llm }  →  config
```

It's a boring layout, and that's the whole point. When a scoring bug shows up, I know it's in `scoring/` and not smeared across one file that does everything.

### Not marrying one LLM vendor

Scoring and drafting need one shared chat interface, but every provider has its own base URL, auth, retry behavior, and token limits. Rather than sprinkle `if provider == "nvidia"` checks all over the app, I hid provider selection behind a factory:

```python
def create_llm_service(config: dict[str, Any]) -> LLMProviderService:
    return get_provider_service_class(get_configured_provider(config))(config)
```

Callers just ask for a service and call `chat_with_llm(...)`. Swapping NVIDIA for a local Ollama model is a config change, not a code change, and when I need to fix a provider's retry quirk I fix it in one place.

**This is the challenge that actually cost me time.** Local models are messy. My first version batched ten job descriptions plus the resume into one giant scoring prompt and asked for a JSON array back. On local Ollama it fell apart. The prompts were slow, one malformed response wasted the entire batch, and if I stopped a run halfway I lost *everything* because results were only written at the very end. I reworked it to score one job per request, expect one JSON object back, and save immediately after each result. Now a stopped run keeps everything it already scored, and one bad reply kills one job instead of thirty. Not clever. Just the thing that made it usable.

### The honest-tailoring problem

This is the part I care about most.

Tailoring is subjective and high-stakes. Tell an LLM to "improve this resume for this job" and it'll cheerfully invent leadership experience, round your two years up to five, and echo every keyword in the posting whether you've earned it or not. That's not a feature. That's how people get caught in interviews.

So I didn't control tailoring with a one-off prompt. I controlled it with an **Agent Skill**: a self-contained bundle of instructions, references, and a checklist, versioned in the repo like code.

```
skills/job-application-tailor/
  SKILL.md                                # workflow + truthful-rewrite rules
  references/resume-tailoring.md          # detailed resume guidance
  references/cover-letter-tailoring.md    # detailed cover-letter guidance
  assets/application-output-checklist.md  # final-pass quality checklist
```

The rule the whole thing rests on is one sentence:

> Mirror the job description's language *only* where the candidate actually has that experience. Never add experience, years, credentials, or leadership the source resume doesn't support.

When tailoring runs, the app loads this skill, injects it into the drafting prompts, and writes a small manifest file next to the outputs so every generated application is traceable back to the exact skill and job it came from. Treating that skill as versioned logic, instead of a prompt buried in code, is what lets me trust the output.

### Making the file actually downloadable

A tailored resume PDF is useless if you can't get it out of the app. The plain ADK web entrypoint didn't give me the download behavior I wanted, so I wrapped the ADK app in a thin FastAPI layer that adds explicit `/downloads/...` routes. They try normal artifact retrieval first and fall back to the session's output files, so the PDFs stay reachable whether I'm running locally or on Cloud Run. Bonus: users only ever see clean download links, never internal storage paths.

One more thing I'll mention because a graded submission should: none of this leaks secrets. API keys are injected in memory only at runtime, never written into session files or committed to the repo. The shipped example config has blank key fields, `.gitignore` covers the sensitive paths, and every session is isolated to its own folder so concurrent users can't see each other's resumes or outputs.

---

## What's Next

I'd rather be straight about the rough edges than oversell it:

- **Discovery leans on good career URLs.** Trusting company pages first is precise, but it depends on the quality of each URL and on detecting the applicant-tracking listing pages. JavaScript-heavy career sites can still hide postings. A rendered-browser fallback is the obvious next step, but only as a fallback, not the default.
- **City names are ambiguous.** Location matching uses offline geographic data (no external geocoding calls, which keeps it fast and cheap to deploy), but genuinely ambiguous city names are still handled with heuristics.
- **Small local models stay the weak link.** Tiny models still sometimes wrap their JSON in prose or code fences. The scorer now shrugs off a bad reply instead of crashing, but the smallest models are where things wobble.

On the list: shared external storage so artifacts outlive a single session's local disk, that rendered-browser discovery fallback, and surfacing the scoring reasons right in the UI so you can see *why* a job ranked where it did.

---

## Final thoughts

The thing that surprised me most about building this wasn't technical. It was how much of the work went into *restraint*. Every interesting decision was about what the agent should **not** do: not fire off a broad search when a company's own page is right there, not batch thirty jobs into one fragile prompt, not swap in a specialist sub-agent just because it looked good on a diagram, and above all not "improve" a resume by quietly inventing things.

That last one is really the heart of it. It would have been trivial to make the tailoring look more impressive by letting the model stretch the truth. The harder and more useful thing was to wire in a skill that holds the line, and to make every generated document traceable back to it. A job tool people can actually trust is worth more than one that dazzles and gets them caught in the interview.

If I had to compress the whole build into one lesson: the hard part of an agent isn't the model or the framework, both of which are better than they've ever been. It's deciding where the agent's judgment genuinely earns its place, keeping every step something you can read back later, and refusing to let "helpful" slide into "dishonest."

Thanks for reading. The code, setup steps, and architecture diagrams are all in the repo, and there's a short demo video walking through a live run. If you build something similar, I'd genuinely like to hear how you'd steer the discovery step, since that's the part I keep coming back to.
