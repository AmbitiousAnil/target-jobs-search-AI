from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import geonamescache


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

REMOTE_RE = re.compile(r"\b(remote|remote-friendly|remotely|work from anywhere|anywhere|worldwide|global|distributed)\b", re.IGNORECASE)
REMOTE_NEGATIVE_RE = re.compile(r"\b(not|non|no)\s+remote\b|\boffice-based\b|\bonsite only\b|\blocal candidates only\b", re.IGNORECASE)
SPONSOR_RE = re.compile(r"\b(visa sponsorship|sponsorship|visa support|work authorization support|relocation support|relocation package)\b", re.IGNORECASE)
SPONSOR_NEGATIVE_RE = re.compile(r"\b(no|not|without|unable to|do not|does not|cannot)\b.{0,40}\b(visa sponsorship|sponsorship|visa support|work authorization support|relocation support|relocation package)\b", re.IGNORECASE)


def candidate_countries(config: dict) -> list[str]:
    countries = config.get("candidate", {}).get("countries", config.get("countries", []))
    if isinstance(countries, str):
        countries = [countries]
    return [str(item).strip() for item in countries if str(item).strip()]


def build_candidate_profile(config: dict) -> str:
    candidate = config.get("candidate", {})
    lines = [f"- {candidate.get('name', 'the candidate')}"]
    if candidate.get("profile"):
        lines.append(f"- {candidate['profile']}")
    if candidate.get("seeking"):
        lines.append(f"- Seeking: {candidate['seeking']}")
    countries = candidate_countries(config)
    if countries:
        lines.append(f"- Preferred locations: {', '.join(countries)}")
    if candidate.get("relocation_note"):
        lines.append(f"- Relocation: {candidate['relocation_note']}")
    if candidate.get("not_suitable"):
        lines.append(f"- NOT suitable: {candidate['not_suitable']}")
    return "\n".join(lines)


def job_location_text(job: dict) -> str:
    parts = [job.get("title", ""), job.get("extracted_title", ""), job.get("location", ""), job.get("location_remote", ""), job.get("region", ""), job.get("url", ""), job.get("content", ""), job.get("snippet", "")]
    return "\n".join(str(part) for part in parts if part)


def normalize_location_fragment(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    lowered = ascii_value.lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", lowered)).strip()


@lru_cache(maxsize=1)
def location_indexes() -> tuple[dict[str, set[str]], dict[str, str]]:
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
        for alias in {country_name, country.get("iso"), country.get("iso3"), country.get("fips")}:
            normalized_alias = normalize_location_fragment(alias or "")
            if normalized_alias:
                fragment_to_countries.setdefault(normalized_alias, set()).add(iso_code)
    for alias, iso_code in _COMMON_COUNTRY_ALIASES.items():
        fragment_to_countries.setdefault(normalize_location_fragment(alias), set()).add(iso_code)
    for city in gc.get_cities().values():
        country_code = str(city.get("countrycode") or "").upper()
        if country_code not in iso_to_name:
            continue
        for city_name in [city.get("name"), *(city.get("alternatenames") or [])]:
            normalized_city = normalize_location_fragment(city_name or "")
            if normalized_city and len(normalized_city) >= 3 and len(normalized_city.split()) <= 5:
                fragment_to_countries.setdefault(normalized_city, set()).add(country_code)
    return fragment_to_countries, iso_to_name


def extract_location_fragments(text: str, max_words: int = 5) -> set[str]:
    words = normalize_location_fragment(text).split()
    fragments: set[str] = set()
    for start in range(len(words)):
        for width in range(1, max_words + 1):
            stop = start + width
            if stop <= len(words):
                fragments.add(" ".join(words[start:stop]))
    return fragments


def resolve_country_filters(countries: list[str]) -> tuple[set[str], set[str]]:
    fragment_to_countries, _ = location_indexes()
    resolved: set[str] = set()
    unresolved: set[str] = set()
    for country in countries:
        normalized = normalize_location_fragment(country)
        if not normalized:
            continue
        matched = fragment_to_countries.get(normalized)
        if matched:
            resolved.update(matched)
        else:
            unresolved.add(normalized)
    return resolved, unresolved


def job_matches_country_filter(job: dict, countries: list[str]) -> bool:
    if not countries:
        return True
    text = job_location_text(job)
    if (REMOTE_RE.search(text) and not REMOTE_NEGATIVE_RE.search(text)) or (SPONSOR_RE.search(text) and not SPONSOR_NEGATIVE_RE.search(text)):
        return True
    normalized_text = normalize_location_fragment(text)
    fragments = extract_location_fragments(text)
    resolved_countries, unresolved_countries = resolve_country_filters(countries)
    fragment_to_countries, _ = location_indexes()
    for fragment in fragments:
        matched = fragment_to_countries.get(fragment)
        if matched and matched & resolved_countries:
            return True
    return any(f" {country} " in f" {normalized_text} " for country in unresolved_countries)


def filter_jobs_by_country(jobs: list[dict], config: dict) -> list[dict]:
    countries = candidate_countries(config)
    if not countries:
        return jobs
    return [job for job in jobs if job_matches_country_filter(job, countries)]

