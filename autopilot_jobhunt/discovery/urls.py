from __future__ import annotations

import re


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
    r"^https?://(jobs\.lever\.co|boards\.greenhouse\.io|apply\.workable\.com|jobs\.smartrecruiters\.com)/[^/?#]+/?(\?.*)?$",
    re.IGNORECASE,
)


def is_job_url(url: str) -> bool:
    return bool(JOB_URL_RE.search(url)) or bool(ATS_JOB_RE.search(url))


def is_ats_listing(url: str) -> bool:
    return bool(ATS_LISTING_RE.match(url))


def discover_job_urls(tf, company: dict, seen_urls: set[str]) -> list[dict]:
    from .fetch import fetch_links_with_rate_limit, fetch_with_rate_limit

    found_urls: set[str] = set()
    response = fetch_with_rate_limit(tf, [company["careers_url"]], format="markdown", links=True)
    if response and response.results:
        links = response.results[0].links
        direct = [link for link in links if is_job_url(link) and link not in seen_urls]
        ats_pages = list({link for link in links if is_ats_listing(link)})
        found_urls.update(direct)
        if ats_pages:
            ats_link_map = fetch_links_with_rate_limit(tf, ats_pages[:5])
            for page_links in ats_link_map.values():
                for link in page_links:
                    if is_job_url(link) and link not in seen_urls:
                        found_urls.add(link)
    return [
        {
            "url": url,
            "title": url.split("/")[-1].replace("-", " ").title(),
            "snippet": "",
            "company": company["name"],
            "location": company["location"],
            "region": company["region"],
        }
        for url in found_urls
    ]

