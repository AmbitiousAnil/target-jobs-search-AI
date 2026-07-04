from __future__ import annotations

import time

from tinyfish import RateLimitError, TinyFish


FETCH_URL_DELAY = 2.5


def fetch_with_rate_limit(tf: TinyFish, urls: list[str], **kwargs):
    for _attempt in range(2):
        try:
            response = tf.fetch.get_contents(urls, **kwargs)
            time.sleep(len(urls) * FETCH_URL_DELAY)
            return response
        except RateLimitError:
            time.sleep(65)
        except Exception:
            time.sleep(len(urls) * FETCH_URL_DELAY)
            return None
    return None


def fetch_links_with_rate_limit(tf: TinyFish, urls: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for index in range(0, len(urls), 10):
        batch = urls[index:index + 10]
        response = fetch_with_rate_limit(tf, batch, format="markdown", links=True)
        if response:
            for item in response.results:
                result[item.url] = item.links
    return result


def fetch_job_details(tf: TinyFish, jobs: list[dict]) -> list[dict]:
    enriched: list[dict] = []
    for index in range(0, len(jobs), 10):
        batch = jobs[index:index + 10]
        response = fetch_with_rate_limit(tf, [job["url"] for job in batch], format="markdown")
        if not response:
            enriched.extend(batch)
            continue
        fetched = {item.url: item for item in response.results}
        for job in batch:
            result = fetched.get(job["url"])
            if result and result.text:
                job["content"] = result.text[:3000]
                job["title"] = result.title or job["title"]
            enriched.append(job)
    return enriched

