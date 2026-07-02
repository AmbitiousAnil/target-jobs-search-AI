import csv
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import geonamescache
from tinyfish import RateLimitError, TinyFish

from job_hunt.llm_utils import chat_with_llm
from job_hunt.log import get_logger

logger = get_logger()

STATE_FILE = Path("state/seen_jobs.json")
LAST_SCAN_FILE = Path("state/last_scan.json")
JOB_HISTORY_FILE = Path("state/job_history.json")
SCAN_STATUS_FILE = Path("state/scan_status.json")

JOB_URL_RE = re.compile(
    r"/(job|jobs|opening|openings|position|positions|vacancy|vacancies|role|roles|apply)"
    r"/[a-zA-Z0-9_%@.-]{4,}",
    re.IGNORECASE,
)
ATS_JOB_RE = re.compile(
    r"(greenhouse\.io/.+/jobs/\d+"
    r"|lever\.co/[^/]+/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
    r"|myworkdayjobs\.com/[^?#]+"
    r"|smartrecruiters\.com/[^/]+/[A-Z0-9]+"
    r"|ashbyhq\.com/[^/]+/[a-f0-9-]{32,})",
    re.IGNORECASE,
)
ATS_LISTING_RE = re.compile(
    r"^https?://(jobs\.lever\.co|boards\.greenhouse\.io|apply\.workable\.com"
    r"|jobs\.smartrecruiters\.com)/[^/?#]+/?(\?.*)?$",
    re.IGNORECASE,
)

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

Score bands:
- 90-100: Very strong match with few truthful gaps.
- 80-89: Strong match with some missing keywords or domain gaps.
- 70-79: Plausible match but would need targeted resume rewriting.
- 60-69: Partial match with important gaps.
- Below 60: Weak match unless the candidate has unexpressed experience.

Output:
{{
  "score": 0-100,
  "title": "extracted job title",
  "stack": "key tech from JD (comma-separated, max 6 items)",
  "location_remote": "location + remote policy",
  "reason": "one sentence why this fits or doesn't fit the candidate",
  "worth_applying": true/false
}}

Set worth_applying=true only if score >= {min_score}.
The reason must briefly mention the strongest matching evidence and the biggest gap or risk.
Return exactly one object for this single job. Output ONLY the JSON object."""

EXPORT_FIELDS = [
    "Company", "Role", "Location", "Application URL",
    "Score (%)", "Stack", "Region", "Reason", "Worth Applying", "Scan Date",
]

_COMMON_COUNTRY_ALIASES = {
    "uk": "GB",
    "britain": "GB",
    "great britain": "GB",
    "england": "GB",
    "usa": "US",
    "us": "US",
    "united states of america": "US",
    "america": "US",
    "uae": "AE",
}

_CSV_SAFE_TRANSLATION = str.maketrans(
    {
        "\u2192": "->",
        "\u2190": "<-",
        "\u2014": "-",
        "\u2013": "-",
        "\u2022": "-",
        "\u2026": "...",
        "\u2019": "'",
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u00a0": " ",
    }
)


def _sanitize_csv_text(value: object) -> str:
    text = str(value or "")
    text = text.translate(_CSV_SAFE_TRANSLATION)
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    return " ".join(text.split())

REMOTE_RE = re.compile(
    r"\b(remote|remote-friendly|remotely|work from anywhere|anywhere|worldwide|global|distributed)\b",
    re.IGNORECASE,
)
REMOTE_NEGATIVE_RE = re.compile(
    r"\b(not|non|no)\s+remote\b|\boffice-based\b|\bonsite only\b|\blocal candidates only\b",
    re.IGNORECASE,
)
SPONSOR_RE = re.compile(
    r"\b(visa sponsorship|sponsorship|visa support|work authorization support|relocation support|relocation package)\b",
    re.IGNORECASE,
)
SPONSOR_NEGATIVE_RE = re.compile(
    r"\b(no|not|without|unable to|do not|does not|cannot)\b.{0,40}"
    r"\b(visa sponsorship|sponsorship|visa support|work authorization support|relocation support|relocation package)\b",
    re.IGNORECASE,
)


def _build_candidate_profile(config: dict) -> str:
    cand = config.get("candidate", {})
    name = cand.get("name", "the candidate")
    profile = cand.get("profile", "")
    seeking = cand.get("seeking", "")
    not_suitable = cand.get("not_suitable", "")
    relocation_note = cand.get("relocation_note", "")
    countries = _candidate_countries(config)

    lines = [f"- {name}"]
    if profile:
        lines.append(f"- {profile}")
    if seeking:
        lines.append(f"- Seeking: {seeking}")
    if countries:
        lines.append(f"- Preferred locations: {', '.join(countries)}")
    if relocation_note:
        lines.append(f"- Relocation: {relocation_note}")
    if not_suitable:
        lines.append(f"- NOT suitable: {not_suitable}")
    return "\n".join(lines)


def _candidate_countries(config: dict) -> list[str]:
    countries = config.get("candidate", {}).get("countries", config.get("countries", []))
    if isinstance(countries, str):
        countries = [countries]
    return [str(c).strip() for c in countries if str(c).strip()]


def _job_location_text(job: dict) -> str:
    parts = [
        job.get("title", ""),
        job.get("extracted_title", ""),
        job.get("location", ""),
        job.get("location_remote", ""),
        job.get("region", ""),
        job.get("url", ""),
        job.get("content", ""),
        job.get("snippet", ""),
    ]
    return "\n".join(str(part) for part in parts if part)


def _normalize_location_fragment(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    lowered = ascii_value.lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", lowered)).strip()


def _normalized_word_count(value: str) -> int:
    normalized = _normalize_location_fragment(value)
    if not normalized:
        return 0
    return len(normalized.split())


@lru_cache(maxsize=1)
def _location_indexes() -> tuple[dict[str, set[str]], dict[str, str]]:
    gc = geonamescache.GeonamesCache(min_city_population=5000)
    countries = gc.get_countries()

    fragment_to_countries: dict[str, set[str]] = {}
    iso_to_name: dict[str, str] = {}

    for country in countries.values():
        iso_code = str(country.get("iso") or "").upper()
        country_name = str(country.get("name") or "").strip()
        if not iso_code or not country_name:
            continue

        iso_to_name[iso_code] = country_name
        aliases = {
            country_name,
            country.get("iso"),
            country.get("iso3"),
            country.get("fips"),
        }
        for alias in aliases:
            normalized_alias = _normalize_location_fragment(alias or "")
            if normalized_alias:
                fragment_to_countries.setdefault(normalized_alias, set()).add(iso_code)

    for alias, iso_code in _COMMON_COUNTRY_ALIASES.items():
        fragment_to_countries.setdefault(_normalize_location_fragment(alias), set()).add(iso_code)

    for city in gc.get_cities().values():
        country_code = str(city.get("countrycode") or "").upper()
        if country_code not in iso_to_name:
            continue

        city_names = [city.get("name"), *(city.get("alternatenames") or [])]
        for city_name in city_names:
            normalized_city = _normalize_location_fragment(city_name or "")
            if not normalized_city or len(normalized_city) < 3 or _normalized_word_count(normalized_city) > 5:
                continue
            fragment_to_countries.setdefault(normalized_city, set()).add(country_code)

    return fragment_to_countries, iso_to_name


def _extract_location_fragments(text: str, max_words: int = 5) -> set[str]:
    words = _normalize_location_fragment(text).split()
    if not words:
        return set()

    fragments: set[str] = set()
    for start in range(len(words)):
        for width in range(1, max_words + 1):
            stop = start + width
            if stop > len(words):
                break
            fragments.add(" ".join(words[start:stop]))
    return fragments


def _resolve_country_filters(countries: list[str]) -> tuple[set[str], set[str]]:
    fragment_to_countries, _ = _location_indexes()
    resolved: set[str] = set()
    unresolved: set[str] = set()

    for country in countries:
        normalized_country = _normalize_location_fragment(country)
        if not normalized_country:
            continue
        matched = fragment_to_countries.get(normalized_country)
        if matched:
            resolved.update(matched)
        else:
            unresolved.add(normalized_country)

    return resolved, unresolved


def _contains_location_fragment(text: str, fragment: str) -> bool:
    normalized_fragment = _normalize_location_fragment(fragment)
    if not normalized_fragment:
        return False
    return f" {normalized_fragment} " in f" {text} "


def job_matches_country_filter(job: dict, countries: list[str]) -> bool:
    if not countries:
        return True

    text = _job_location_text(job)
    remote_ok = REMOTE_RE.search(text) and not REMOTE_NEGATIVE_RE.search(text)
    sponsor_ok = SPONSOR_RE.search(text) and not SPONSOR_NEGATIVE_RE.search(text)
    if remote_ok or sponsor_ok:
        return True

    normalized_text = _normalize_location_fragment(text)
    fragments = _extract_location_fragments(text)
    resolved_countries, unresolved_countries = _resolve_country_filters(countries)
    fragment_to_countries, _ = _location_indexes()

    for fragment in fragments:
        matched_countries = fragment_to_countries.get(fragment)
        if matched_countries and matched_countries & resolved_countries:
            return True

    return any(
        _contains_location_fragment(normalized_text, country)
        for country in unresolved_countries
    )


def filter_jobs_by_country(jobs: list[dict], config: dict) -> list[dict]:
    countries = _candidate_countries(config)
    if not countries:
        return jobs

    filtered = [job for job in jobs if job_matches_country_filter(job, countries)]
    skipped = len(jobs) - len(filtered)
    if skipped:
        logger.info(
            f"  Country filter kept {len(filtered)}/{len(jobs)} job(s) "
            f"for {', '.join(countries)}; remote/sponsorship jobs pass automatically"
        )
    return filtered


def is_job_url(url: str) -> bool:
    return bool(JOB_URL_RE.search(url)) or bool(ATS_JOB_RE.search(url))


def is_ats_listing(url: str) -> bool:
    return bool(ATS_LISTING_RE.match(url))


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"seen_urls": []}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _write_scan_status(payload: dict) -> None:
    SCAN_STATUS_FILE.parent.mkdir(exist_ok=True)
    payload_to_write = payload.copy()
    payload_to_write["last_updated"] = datetime.now(timezone.utc).isoformat()
    SCAN_STATUS_FILE.write_text(json.dumps(payload_to_write, indent=2), encoding="utf-8")


_FETCH_URL_DELAY = 2.5


def _fetch_with_ratelimit(tf: TinyFish, urls: list[str], **kwargs):
    for attempt in range(2):
        try:
            resp = tf.fetch.get_contents(urls, **kwargs)
            time.sleep(len(urls) * _FETCH_URL_DELAY)
            return resp
        except RateLimitError:
            logger.warning("Fetch rate-limited - waiting 65s before retry...")
            time.sleep(65)
        except Exception as e:
            logger.error(f"Fetch error for {urls[:1]}: {e}")
            time.sleep(len(urls) * _FETCH_URL_DELAY)
            return None
    return None


def _fetch_links(tf: TinyFish, urls: list[str]) -> dict[str, list[str]]:
    result = {}
    for i in range(0, len(urls), 10):
        batch = urls[i: i + 10]
        resp = _fetch_with_ratelimit(tf, batch, format="markdown", links=True)
        if resp:
            for r in resp.results:
                result[r.url] = r.links
    return result


def discover_job_urls(tf: TinyFish, company: dict, seen_urls: set) -> list[dict]:
    found_urls: set[str] = set()

    logger.debug(f"  [{company['name']}] Fetching careers page: {company['careers_url']}")
    resp = _fetch_with_ratelimit(tf, [company["careers_url"]], format="markdown", links=True)
    if resp and resp.results:
        links = resp.results[0].links
        direct = [link for link in links if is_job_url(link) and link not in seen_urls]
        ats_pages = list({link for link in links if is_ats_listing(link)})
        found_urls.update(direct)
        logger.debug(f"  [{company['name']}] Careers page: {len(direct)} direct job links, {len(ats_pages)} ATS listing pages")

        if ats_pages:
            logger.debug(f"  [{company['name']}] Expanding {len(ats_pages)} ATS listing page(s)...")
            ats_link_map = _fetch_links(tf, ats_pages[:5])
            ats_jobs = 0
            for page_links in ats_link_map.values():
                for link in page_links:
                    if is_job_url(link) and link not in seen_urls:
                        found_urls.add(link)
                        ats_jobs += 1
            logger.debug(f"  [{company['name']}] ATS expansion: {ats_jobs} additional job links")

    new = [
        {
            "url": u,
            "title": u.split("/")[-1].replace("-", " ").title(),
            "snippet": "",
            "company": company["name"],
            "location": company["location"],
            "region": company["region"],
        }
        for u in found_urls
    ]
    return new


def fetch_job_details(tf: TinyFish, jobs: list[dict]) -> list[dict]:
    enriched = []
    for i in range(0, len(jobs), 10):
        batch = jobs[i: i + 10]
        urls = [j["url"] for j in batch]
        logger.debug(f"  Fetching details for {len(batch)} job(s): {[j['title'][:40] for j in batch]}")
        resp = _fetch_with_ratelimit(tf, urls, format="markdown")
        if not resp:
            enriched.extend(batch)
            continue
        fetched = {r.url: r for r in resp.results}
        for job in batch:
            r = fetched.get(job["url"])
            if r and r.text:
                job["content"] = r.text[:3000]
                job["title"] = r.title or job["title"]
                logger.debug(f"    Fetched '{job['title']}' - {len(r.text)} chars")
            else:
                logger.debug(f"    No content for: {job['url']}")
            enriched.append(job)
    return enriched


def score_jobs(
    jobs: list[dict],
    resume: str,
    config: dict,
    on_job_started=None,
    on_scored_job=None,
) -> list[dict]:
    if not jobs:
        return []

    min_score = config.get("candidate", {}).get("min_score", 55)
    candidate_profile = _build_candidate_profile(config)
    logger.debug(
        f"  Scoring {len(jobs)} job(s) via LLM "
        f"(1 JD per request, min_score={min_score})..."
    )

    results = []
    passing = 0
    for idx, job in enumerate(jobs, 1):
        if on_job_started:
            on_job_started(idx, job.copy(), len(jobs))
        prompt = SCORE_PROMPT.format(
            candidate_profile=candidate_profile,
            resume_summary=resume[:2500],
            company=job["company"],
            location=job["location"],
            title=job["title"],
            url=job["url"],
            job_text=job.get("content", job.get("snippet", ""))[:1500],
            min_score=min_score,
        )

        logger.debug(f"    Scoring job {idx}/{len(jobs)}: {job['title']}")
        t0 = time.time()
        try:
            raw = chat_with_llm(
                config,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            elapsed = time.time() - t0
            start, end = raw.find("{"), raw.rfind("}") + 1
            if start == -1:
                logger.error(f"    LLM returned no JSON object for: {job['url']}")
                continue
            item = json.loads(raw[start:end])
            logger.debug(f"    LLM scoring complete in {elapsed:.1f}s for: {job['title']}")
        except Exception as e:
            logger.error(f"    Scoring error for {job['url']}: {e}")
            continue

        score = item.get("score", 0)
        title = item.get("title", job["title"])
        reason = item.get("reason", "")
        worth = item.get("worth_applying", False)
        logger.debug(f"    [{score:3d}] {title} - {reason[:80]}")
        scored_job = job.copy()
        scored_job.update(
            {
                "score": score,
                "extracted_title": title,
                "stack": item.get("stack", ""),
                "location_remote": item.get("location_remote", job["location"]),
                "reason": reason,
                "worth_applying": worth,
            }
        )
        results.append(scored_job)
        if on_scored_job:
            on_scored_job(scored_job.copy())
        if worth:
            passing += 1

    logger.debug(f"  {passing}/{len(results)} jobs passed min_score threshold")
    return sorted(results, key=lambda x: x["score"], reverse=True)


def _export_to_csv(jobs: list[dict], label: str, quiet: bool = False) -> Path:
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = Path("output") / f"jobs_{date_str}.csv"
    out_path.parent.mkdir(exist_ok=True)

    def _row(j: dict) -> dict:
        worth = j.get("worth_applying")
        return {
            "Company": _sanitize_csv_text(j.get("company", "")),
            "Role": _sanitize_csv_text(j.get("extracted_title") or j.get("title", "")),
            "Location": _sanitize_csv_text(j.get("location_remote") or j.get("location", "")),
            "Application URL": _sanitize_csv_text(j.get("url", "")),
            "Score (%)": j.get("score", ""),
            "Stack": _sanitize_csv_text(j.get("stack", "")),
            "Region": _sanitize_csv_text(j.get("region", "")),
            "Reason": _sanitize_csv_text(j.get("reason", "")),
            "Worth Applying": "Yes" if worth else ("No" if worth is False else ""),
            "Scan Date": _sanitize_csv_text(j.get("scan_date", "")),
        }

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        for j in jobs:
            writer.writerow(_row(j))

    if not quiet:
        logger.info(f"Results exported to CSV ({label}): {out_path}")
    return out_path


def _load_job_history() -> list[dict]:
    if JOB_HISTORY_FILE.exists():
        try:
            return json.loads(JOB_HISTORY_FILE.read_text())
        except Exception:
            return []
    return []


def _persist_scan_artifacts(scored_jobs: list[dict], history: list[dict], quiet: bool = False):
    LAST_SCAN_FILE.parent.mkdir(exist_ok=True)
    LAST_SCAN_FILE.write_text(json.dumps(scored_jobs, indent=2))
    JOB_HISTORY_FILE.write_text(json.dumps(history, indent=2))
    if scored_jobs:
        return _export_to_csv(scored_jobs, "scan results", quiet=quiet)
    return None


def run_scan(config: dict, companies: list[dict]) -> None:
    scan_start = time.time()
    total = len(companies)
    min_score = config.get("candidate", {}).get("min_score", 55)
    top_n = config.get("candidate", {}).get("top_n", 5)
    status = {
        "status": "running",
        "phase": "starting",
        "message": "Initializing scan...",
        "companies_total": total,
        "companies_scanned": 0,
        "company_index": 0,
        "company_name": None,
        "company_jobs_total": 0,
        "jobs_discovered_total": 0,
        "jobs_scored_total": 0,
        "jobs_above_threshold_total": 0,
        "current_job_index": 0,
        "current_job_title": None,
        "errors": [],
    }

    def update_status(**updates) -> None:
        status.update(updates)
        _write_scan_status(status)

    update_status(message="Initializing scan...")
    logger.info(f"=== Scan started - {total} companies to check ===")
    logger.info(f"Candidate: {config.get('candidate', {}).get('name', 'unknown')}")
    logger.info(f"Min score: {config.get('candidate', {}).get('min_score', 55)} | Top N: {config.get('candidate', {}).get('top_n', 5)}")
    provider = config.get("llm_provider") or "openrouter"
    model_by_provider = {
        "openrouter": config.get("openrouter_model", "default"),
        "nvidia": config.get("nvidia_model", "default"),
        "anthropic": config.get("anthropic_model", "default"),
        "claude_cli": config.get("claude_cli_model") or "claude default",
    }
    logger.info(f"LLM provider: {provider} | Model: {model_by_provider.get(provider, 'default')}")

    try:
        tf = TinyFish(api_key=config["tinyfish_api_key"])
        logger.debug("TinyFish client initialised")
    except Exception as e:
        logger.error(f"TinyFish init error: {e}")
        update_status(
            status="failed",
            phase="failed",
            message=f"TinyFish init failed: {e}",
            errors=[str(e)],
        )
        return

    resume_path = Path(config.get("candidate", {}).get("resume_path", "resume/YOUR_RESUME.md"))
    resume = resume_path.read_text()
    logger.debug(f"Resume loaded: {resume_path} ({len(resume)} chars)")
    update_status(message="Loaded scan state and resume.")

    min_score = config.get("candidate", {}).get("min_score", 55)
    top_n = config.get("candidate", {}).get("top_n", 5)

    state = load_state()
    seen_urls: set = set(state.get("seen_urls", []))
    logger.info(f"State loaded - {len(seen_urls)} previously seen URLs")

    scored_jobs_by_url: dict[str, dict] = {}
    history_by_url = {
        job["url"]: job for job in _load_job_history()
        if isinstance(job, dict) and job.get("url")
    }
    errors: list[str] = []
    companies_scanned = 0
    companies_with_jobs = 0
    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def persist_jobs(jobs_to_persist: list[dict], *, immediate: bool) -> None:
        changed = False
        for job in jobs_to_persist:
            if not isinstance(job, dict) or not job.get("url"):
                continue
            persisted_job = job.copy()
            persisted_job["scan_date"] = scan_date
            previous = scored_jobs_by_url.get(persisted_job["url"])
            if previous != persisted_job:
                changed = True
            scored_jobs_by_url[persisted_job["url"]] = persisted_job
            history_by_url[persisted_job["url"]] = persisted_job
        if changed:
            _persist_scan_artifacts(
                list(scored_jobs_by_url.values()),
                list(history_by_url.values()),
                quiet=True,
            )
            update_status(
                jobs_scored_total=len(scored_jobs_by_url),
                jobs_above_threshold_total=len(
                    [job for job in scored_jobs_by_url.values() if (job.get("score") or 0) >= min_score]
                ),
            )
            if immediate and jobs_to_persist:
                latest = jobs_to_persist[-1]
                logger.debug(
                    "    Persisted score for: "
                    f"{latest.get('extracted_title') or latest.get('title', latest.get('url', '?'))}"
                )

    for idx, company in enumerate(companies, 1):
        update_status(
            phase="discovering",
            company_index=idx,
            company_name=company["name"],
            companies_scanned=companies_scanned,
            company_jobs_total=0,
            current_job_index=0,
            current_job_title=None,
            message=f"Discovering jobs for {company['name']} ({idx}/{total})",
        )
        logger.info(f"[{idx}/{total}] Scanning {company['name']}...")
        try:
            new_jobs = discover_job_urls(tf, company, seen_urls)
            if not new_jobs:
                logger.info("  No new job URLs found")
                companies_scanned += 1
                update_status(
                    companies_scanned=companies_scanned,
                    message=f"No new job URLs found for {company['name']}.",
                )
                continue

            logger.info(f"  {len(new_jobs)} new job URL(s) - fetching details...")
            update_status(
                phase="fetching",
                jobs_discovered_total=status["jobs_discovered_total"] + len(new_jobs),
                company_jobs_total=len(new_jobs),
                message=f"Fetching details for {len(new_jobs)} discovered URLs at {company['name']}.",
            )
            new_jobs = fetch_job_details(tf, new_jobs)
            seen_urls.update(j["url"] for j in new_jobs)
            new_jobs = filter_jobs_by_country(new_jobs, config)
            if not new_jobs:
                logger.info("  No jobs left after country filter")
                companies_scanned += 1
                update_status(
                    companies_scanned=companies_scanned,
                    company_jobs_total=0,
                    message=f"No jobs left after country filter for {company['name']}.",
                )
                continue

            update_status(
                phase="scoring",
                company_jobs_total=len(new_jobs),
                current_job_index=0,
                current_job_title=None,
                message=f"Scoring {len(new_jobs)} jobs for {company['name']}.",
            )
            logger.info(f"  Scoring {len(new_jobs)} job(s)...")
            scored: list[dict] = []
            try:
                scored = score_jobs(
                    new_jobs,
                    resume,
                    config,
                    on_job_started=lambda job_idx, job, total_jobs: update_status(
                        phase="scoring",
                        company_jobs_total=total_jobs,
                        current_job_index=job_idx,
                        current_job_title=job.get("title"),
                        message=f"Scoring job {job_idx}/{total_jobs} for {company['name']}: {job.get('title')}",
                    ),
                    on_scored_job=lambda job: persist_jobs([job], immediate=True),
                )
            except Exception as score_err:
                logger.error(f"  Scoring failed: {score_err}")
                errors.append(f"⚠️ Scoring failed for {company['name']}: {score_err}")
                update_status(
                    errors=list(errors),
                    message=f"Scoring failed for {company['name']}: {score_err}",
                )
                logger.warning(f"  Saving {len(new_jobs)} unscored job(s) as fallback")
                scored = new_jobs

            if scored:
                persist_jobs(scored, immediate=False)
                companies_with_jobs += 1
                titles = [j.get("extracted_title") or j.get("title", "?") for j in scored[:3]]
                logger.info(f"  {len(scored)} job(s) saved: {', '.join(titles)}{' ...' if len(scored) > 3 else ''}")

            companies_scanned += 1
            update_status(
                companies_scanned=companies_scanned,
                current_job_index=0,
                current_job_title=None,
                message=f"Completed {company['name']} ({idx}/{total}).",
            )

        except Exception as company_err:
            msg = f"❌ {company['name']}: {company_err}"
            errors.append(msg)
            logger.error(f"  Company scan failed: {company_err}")
            update_status(
                errors=list(errors),
                message=f"Company scan failed for {company['name']}: {company_err}",
            )
            continue

    state["seen_urls"] = list(seen_urls)
    state["last_scan"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    logger.debug("State saved")

    all_scored_jobs = list(scored_jobs_by_url.values())
    top_jobs = sorted(
        [j for j in all_scored_jobs if j.get("score", 0) >= min_score],
        key=lambda x: x.get("score", 0), reverse=True
    )[:top_n]
    csv_path = _persist_scan_artifacts(
        all_scored_jobs,
        list(history_by_url.values()),
        quiet=False,
    ) if all_scored_jobs else None
    logger.debug(f"Last scan saved: {len(all_scored_jobs)} total jobs -> {LAST_SCAN_FILE}")
    logger.debug(f"Job history updated: {len(history_by_url)} total entries")

    elapsed = time.time() - scan_start
    logger.info(
        f"=== Scan complete - {companies_scanned}/{total} companies, "
        f"{len(all_scored_jobs)} jobs found, {len(top_jobs)} top matches "
        f"({elapsed / 60:.1f} min) ==="
    )

    update_status(
        status="completed",
        phase="completed",
        companies_scanned=companies_scanned,
        company_index=total,
        current_job_index=0,
        current_job_title=None,
        jobs_scored_total=len(all_scored_jobs),
        jobs_above_threshold_total=len(
            [job for job in all_scored_jobs if (job.get("score") or 0) >= min_score]
        ),
        errors=list(errors),
        message=f"Scan completed: {len(all_scored_jobs)} jobs scored across {companies_scanned}/{total} companies.",
        last_scan_path=str(LAST_SCAN_FILE),
        csv_path=str(csv_path) if csv_path else None,
        top_matches_count=len(top_jobs),
        companies_with_jobs=companies_with_jobs,
    )

    if top_jobs:
        logger.info("Top matches:")
        for j in top_jobs:
            logger.info(f"  [{j.get('score', '?'):3}] {j.get('extracted_title') or j.get('title')} @ {j['company']} - {j.get('reason', '')[:80]}")

    if csv_path:
        logger.info(f"Scan results saved to CSV: {csv_path}")

    if not top_jobs:
        logger.info("No matching jobs found today.")
        return
