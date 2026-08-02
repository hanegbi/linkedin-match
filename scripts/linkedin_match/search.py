"""Web-search fallback (Mojeek) to find a company's careers page."""

import logging
import re
import threading
import time
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("linkedin_match.search")

MOJEEK_URL = "https://www.mojeek.com/search"
MIN_INTERVAL = 2.0
ENABLED = True

_AGGREGATORS = re.compile(
    r"(linkedin|glassdoor|indeed|ziprecruiter|wikipedia|facebook|x\.com|twitter|youtube|"
    r"crunchbase|bloomberg|themuse|builtin|wellfound|angellist|google|theorg|pitchbook|"
    r"tracxn|leadiq|rocketreach|comparably|zippia|mojeek|getro|levels\.fyi|remoterocketship|"
    r"cbinsights|dnb\.com|finance\.yahoo|globaldata|casino|readwrite|masaisrael|devjobs|"
    r"startupnation|finder\.|reddit|medium\.com|timesofisrael|calcalist|geektime)",
    re.I,
)
_ATS = re.compile(
    r"(jobs\.lever\.co/[\w-]+|boards\.greenhouse\.io/[\w-]+|job-boards\.greenhouse\.io/[\w-]+|"
    r"jobs\.ashbyhq\.com/[\w-]+|apply\.workable\.com/[\w-]+|comeet\.com/jobs/[\w-]+|"
    r"smartrecruiters\.com/[\w-]+)",
    re.I,
)
_CAREERS_PATH = re.compile(r"career|job|position|vacanc|join", re.I)

_lock = threading.Lock()
_last_call = [0.0]


def _throttle() -> None:
    """Serialize and space out search requests to stay polite and unblocked."""
    with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()


def _core(name: str) -> str:
    """Return the first alphanumeric token of a name for host matching."""
    parts = [p for p in re.split(r"[^A-Za-z0-9]", name) if p]
    return re.sub(r"[^a-z0-9]", "", parts[0].casefold()) if parts else ""


def mojeek_results(query: str, session: requests.Session) -> list[str]:
    """Return ranked result URLs from a Mojeek search, or empty on failure."""
    _throttle()
    try:
        response = session.get(MOJEEK_URL, params={"q": query}, timeout=20)
    except requests.RequestException as error:
        logger.debug("mojeek %s failed: %s", query, error)
        return []
    if not response.ok:
        logger.debug("mojeek %s status %s", query, response.status_code)
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    return [a.get("href") for a in soup.select("a.title") if a.get("href")]


def pick_careers(name: str, results: list[str]) -> Optional[str]:
    """Choose the best careers/ATS URL (or official domain) from search results.

    Prefers ATS boards and careers paths on the company's own domain over news
    and aggregator pages; falls back to the official homepage to crawl later.
    """
    core = _core(name)
    best: Optional[str] = None
    best_score = float("-inf")
    for index, url in enumerate(results):
        if not url.startswith("http") or _AGGREGATORS.search(url):
            continue
        host = re.sub(r"[^a-z0-9]", "", urlparse(url).netloc.casefold())
        path = urlparse(url).path
        score = -index * 0.1
        if _ATS.search(url):
            score += 10
        if _CAREERS_PATH.search(path):
            score += 5
        if core and core in host:
            score += 4
        if score > best_score:
            best_score, best = score, url
    return best


def search_company(name: str, session: requests.Session, region: str = "Israel") -> Optional[str]:
    """Search the web for a company's careers page, biased to a region.

    Returns a careers/ATS URL or an official homepage, or None if nothing
    relevant is found.
    """
    if not ENABLED:
        return None
    results = mojeek_results(f"{name} careers {region}".strip(), session)
    if not results:
        results = mojeek_results(f"{name} careers", session)
    return pick_careers(name, results)
