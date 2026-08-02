"""HTTP fetchers that pull open jobs from hosted ATS providers into Job models."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, Union

import requests

from linkedin_match.models import Job

logger = logging.getLogger("linkedin_match.fetchers")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT = 15
RETRIES = 2


def make_session(pool_size: int = 32) -> requests.Session:
    """Build a requests Session with a realistic browser User-Agent.

    Scraping hits hundreds of distinct company domains concurrently from a
    thread pool that all share this one session, so the connection pool must be
    sized to match (or exceed) the worker count. ``requests``' default pool
    (10 connections, 10 cached per-host pools) silently caps concurrency well
    below what ``--workers`` requests — raising ``--workers`` past ~10 did
    nothing before this, since threads just queued for a free pool slot.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    adapter = requests.adapters.HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _request(session: requests.Session, method: str, url: str, **kwargs) -> Optional[requests.Response]:
    """Issue an HTTP request with a small retry loop, logging and returning None on failure."""
    for attempt in range(RETRIES + 1):
        try:
            response = session.request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as error:
            logger.debug("%s %s failed (attempt %s): %s", method, url, attempt + 1, error)
            continue
        if response.status_code == 404:
            return response
        if response.ok:
            return response
        logger.debug("%s %s returned %s", method, url, response.status_code)
    return None


def _clean(text: Optional[str]) -> str:
    """Collapse whitespace in a possibly-None string."""
    if not text:
        return ""
    return " ".join(text.split())


def _posted_date(value: Union[str, int, float, None]) -> Optional[str]:
    """Normalize an ATS posting date to YYYY-MM-DD.

    Accepts an ISO date/datetime string or an epoch value in milliseconds
    (Lever); returns None when the value is missing or unparseable.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).date().isoformat()
        except (ValueError, OverflowError, OSError):
            return None
    return str(value)[:10]


def fetch_greenhouse(session: requests.Session, token: str) -> Optional[list[Job]]:
    """Fetch open jobs from a Greenhouse board, or None if the board is absent."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    response = _request(session, "GET", url)
    if response is None or response.status_code == 404:
        return None
    jobs: list[Job] = []
    for item in response.json().get("jobs", []):
        offices = item.get("offices") or []
        location = (item.get("location") or {}).get("name") or _clean(
            ", ".join(o.get("name", "") for o in offices)
        )
        departments = item.get("departments") or []
        jobs.append(
            Job(
                title=_clean(item.get("title")),
                location=location or None,
                url=item.get("absolute_url"),
                description=_clean(item.get("content"))[:4000],
                department=departments[0].get("name") if departments else None,
                posted_at=_posted_date(item.get("updated_at") or item.get("first_published")),
            )
        )
    return jobs


def fetch_lever(session: requests.Session, token: str) -> Optional[list[Job]]:
    """Fetch open jobs from a Lever postings feed, or None if the account is absent."""
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    response = _request(session, "GET", url)
    if response is None or response.status_code == 404:
        return None
    jobs: list[Job] = []
    for item in response.json():
        categories = item.get("categories") or {}
        jobs.append(
            Job(
                title=_clean(item.get("text")),
                location=categories.get("location"),
                url=item.get("hostedUrl"),
                description=_clean(item.get("descriptionPlain"))[:4000],
                department=categories.get("team") or categories.get("department"),
                employment_type=categories.get("commitment"),
                posted_at=_posted_date(item.get("createdAt")),
            )
        )
    return jobs


def fetch_ashby(session: requests.Session, token: str) -> Optional[list[Job]]:
    """Fetch open jobs from an Ashby job board, or None if the board is absent."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false"
    response = _request(session, "GET", url)
    if response is None or response.status_code == 404:
        return None
    payload = response.json()
    if not isinstance(payload, dict) or "jobs" not in payload:
        return None
    jobs: list[Job] = []
    for item in payload.get("jobs", []):
        jobs.append(
            Job(
                title=_clean(item.get("title")),
                location=item.get("location"),
                url=item.get("jobUrl") or item.get("applyUrl"),
                description=_clean(item.get("descriptionPlain"))[:4000],
                department=item.get("department") or item.get("team"),
                employment_type=item.get("employmentType"),
                posted_at=_posted_date(item.get("publishedAt") or item.get("updatedAt")),
            )
        )
    return jobs


def fetch_workable(session: requests.Session, token: str) -> Optional[list[Job]]:
    """Fetch open jobs from a Workable account, or None if the account is absent."""
    url = f"https://apply.workable.com/api/v3/accounts/{token}/jobs"
    response = _request(session, "POST", url, json={"query": "", "location": [], "department": []})
    if response is None or response.status_code == 404:
        return None
    payload = response.json()
    if not isinstance(payload, dict) or "results" not in payload:
        return None
    jobs: list[Job] = []
    for item in payload.get("results", []):
        location = item.get("location") or {}
        city = location.get("city")
        country = location.get("country")
        where = ", ".join(part for part in (city, country) if part)
        jobs.append(
            Job(
                title=_clean(item.get("title")),
                location=where or None,
                url=f"https://apply.workable.com/{token}/j/{item.get('shortcode')}/"
                if item.get("shortcode")
                else None,
                description="",
                department=item.get("department"),
                employment_type=item.get("type"),
                posted_at=_posted_date(item.get("published_on") or item.get("created_at")),
            )
        )
    return jobs


def fetch_comeet(session: requests.Session, token: str) -> Optional[list[Job]]:
    """Fetch open jobs from a Comeet careers feed, or None if the feed is absent."""
    url = f"https://www.comeet.com/jobs-api/2.1/company/{token}/positions"
    response = _request(session, "GET", url)
    if response is None or response.status_code == 404:
        return None
    payload = response.json()
    if not isinstance(payload, list):
        return None
    jobs: list[Job] = []
    for item in payload:
        location = item.get("location") or {}
        where = location.get("name") or ", ".join(
            part for part in (location.get("city"), location.get("country")) if part
        )
        jobs.append(
            Job(
                title=_clean(item.get("name")),
                location=where or None,
                url=item.get("url_comeet_hosted_page") or item.get("url_active_page"),
                description=_clean(item.get("details", [{}])[0].get("value"))[:4000]
                if item.get("details")
                else "",
                department=item.get("department"),
                employment_type=item.get("employment_type"),
                posted_at=_posted_date(item.get("time_updated") or item.get("updated_at")),
            )
        )
    return jobs


def _balanced_arrays(text: str):
    """Yield top-level array-of-objects JSON substrings via bracket matching.

    Finds a '[' whose first non-space token is '{' (so it tolerates pretty-
    printed arrays), then scans to the matching ']'. String-aware so brackets
    inside quoted values don't break the depth count.
    """
    i = 0
    n = len(text)
    while i < n:
        start = text.find("[", i)
        if start == -1:
            return
        k = start + 1
        while k < n and text[k] in " \t\r\n":
            k += 1
        if k >= n or text[k] != "{":
            i = start + 1
            continue
        depth = 0
        in_str = False
        esc = False
        end = -1
        for j in range(start, n):
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end == -1:
            return
        yield text[start : end + 1]
        i = end + 1


def parse_comeet_hosted(html: str) -> Optional[list[Job]]:
    """Extract positions embedded as JSON in a Comeet hosted careers page.

    Comeet's hosted board (comeet.com/jobs/<name>/<uid>) renders via JS but ships
    the positions as a JSON array in the page. The public positions API is token-
    gated, so we parse the largest embedded array of position objects directly.
    """
    best: list[dict] = []
    for blob in _balanced_arrays(html):
        if not any(m in blob for m in ("comeetapply.com", "url_comeet_hosted_page", "position_name")):
            continue
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        if isinstance(data, list) and data and isinstance(data[0], dict) and "name" in data[0]:
            if len(data) > len(best):
                best = data
    if not best:
        return None
    jobs: list[Job] = []
    for item in best:
        location = item.get("location") or {}
        if isinstance(location, dict):
            where = location.get("name") or ", ".join(
                part for part in (location.get("city"), location.get("country")) if part
            )
        else:
            where = location
        details = item.get("details") or []
        desc = _clean(details[0].get("value")) if details and isinstance(details[0], dict) else ""
        jobs.append(
            Job(
                title=_clean(item.get("name")),
                location=where or None,
                url=item.get("url_comeet_hosted_page") or item.get("url_active_page"),
                description=desc[:4000],
                department=item.get("department"),
                employment_type=item.get("employment_type"),
                posted_at=_posted_date(item.get("time_updated") or item.get("updated_at")),
            )
        )
    return jobs


ATS_FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "workable": fetch_workable,
    "comeet": fetch_comeet,
}
