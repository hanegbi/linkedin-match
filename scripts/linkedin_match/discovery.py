"""Resolve a company's official careers page from its name."""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from linkedin_match.companies import (
    CAREERS_LINK_TERMS,
    CAREERS_URL_PATTERNS,
    DOMAIN_TLDS,
    GENERIC_NAME_WORDS,
)

logger = logging.getLogger("linkedin_match.discovery")

CLEARBIT_SUGGEST = "https://autocomplete.clearbit.com/v1/companies/suggest"
VERIFIED_PATH = Path("verified_domains.json")
MIN_CORE_LEN = 4

_SHARE_HOSTS = re.compile(
    r"(addtoany|facebook|twitter|x\.com|linkedin|instagram|wa\.me|whatsapp|t\.me|telegram|"
    r"sharer|mailto|pinterest|reddit)",
    re.I,
)

_verified: Optional[dict[str, str]] = None


def load_verified(path: Path = VERIFIED_PATH) -> dict[str, str]:
    """Load the manually verified company -> careers URL / domain cache.

    This is the highest-priority source: entries here (typically filled in by a
    one-off web search for ambiguous names) bypass automatic resolution and the
    skip rule entirely.
    """
    global _verified
    if _verified is None:
        try:
            _verified = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _verified = {}
    return _verified


def normalize(text: str) -> str:
    """Strip a string down to lowercase alphanumerics for loose comparison."""
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def name_core(name: str) -> str:
    """Return a company's distinctive core, dropping generic suffix words."""
    words = [w for w in re.split(r"[^a-z0-9]+", name.casefold()) if w]
    significant = [w for w in words if w not in GENERIC_NAME_WORDS]
    return "".join(significant or words)


def is_straightforward(name: str) -> bool:
    """Whether a company name is distinctive enough to resolve by guessing.

    Very short cores (e.g. "Wiz") collide with unrelated domains, so they are
    only trusted when an exact directory match exists, never when guessing.
    """
    return len(name_core(name)) >= MIN_CORE_LEN


def fetch_html(url: str, session: requests.Session, timeout: int = 12) -> Optional[tuple[str, str]]:
    """GET a URL and return its final URL and HTML, or None on any failure."""
    try:
        response = session.get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as error:
        logger.debug("GET %s failed: %s", url, error)
        return None
    if not response.ok or not response.text:
        return None
    return response.url, response.text


def page_represents(name: str, url: str, html: str) -> bool:
    """Heuristically confirm a page belongs to the company by its name core."""
    core = name_core(name)
    if len(core) < 3:
        return True
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string if soup.title else ""
    meta = soup.find("meta", attrs={"property": "og:site_name"})
    site_name = meta.get("content", "") if meta else ""
    haystack = re.sub(r"[^a-z0-9]", "", f"{url} {title} {site_name}".casefold())
    return core in haystack


def clearbit_domain(name: str, session: requests.Session) -> Optional[str]:
    """Resolve an official domain via Clearbit, only on an exact name match."""
    try:
        response = session.get(CLEARBIT_SUGGEST, params={"query": name}, timeout=12)
    except requests.RequestException as error:
        logger.debug("clearbit %s failed: %s", name, error)
        return None
    if not response.ok:
        return None
    target = normalize(name)
    for item in response.json():
        if normalize(item.get("name", "")) == target and item.get("domain"):
            return item["domain"]
    return None


def domain_label(url_or_domain: str) -> str:
    """Return the second-level label of a domain (e.g. 'fireblocks' from a URL)."""
    host = urlparse(url_or_domain).netloc or url_or_domain
    host = host.split(":")[0]
    parts = [p for p in host.split(".") if p and p != "www"]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else ""


_DISCOVERY_FANOUT_WORKERS = 8


def guess_homepage(name: str, session: requests.Session) -> Optional[str]:
    """Probe common TLDs for a homepage that verifiably represents the company.

    Fetches every token/TLD combination concurrently instead of one at a time
    (up to 2 tokens x 7 TLDs = 14 sequential requests previously), but still
    picks the winner in the original token-then-TLD preference order among
    whichever candidates verified, so results are identical to the sequential
    version — only the wall-clock cost changes.
    """
    tokens = [t for t in (re.sub(r"[^a-z0-9-]", "", name.casefold().replace(" ", "")), normalize(name)) if t]
    candidates = [f"https://www.{token}{tld}" for token in dict.fromkeys(tokens) for tld in DOMAIN_TLDS]
    if not candidates:
        return None
    pool = ThreadPoolExecutor(max_workers=_DISCOVERY_FANOUT_WORKERS)
    try:
        futures = [pool.submit(fetch_html, url, session, 8) for url in candidates]
        for future in futures:
            page = future.result()
            if page and page_represents(name, page[0], page[1]):
                return page[0]
        return None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def resolve_homepage(name: str, session: requests.Session) -> Optional[str]:
    """Resolve a confident official homepage, or None when the name is unclear.

    Trusts an exact Clearbit match (verified by fetching the site), then falls
    back to TLD guessing only for distinctive names.
    """
    domain = clearbit_domain(name, session)
    if domain:
        page = fetch_html(f"https://{domain}", session, timeout=8)
        if page and page_represents(name, page[0], page[1]):
            return page[0]
    if is_straightforward(name):
        return guess_homepage(name, session)
    return None


def careers_link_from_html(base_url: str, html: str) -> Optional[str]:
    """Find the best careers/jobs link on a page, preferring explicit hrefs."""
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(base_url).netloc
    best: Optional[str] = None
    best_rank = 0
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        text = " ".join(anchor.get_text().split()).casefold()
        if not any(term in f"{href.casefold()} {text}" for term in CAREERS_LINK_TERMS):
            continue
        absolute = urljoin(base_url, href)
        if _SHARE_HOSTS.search(urlparse(absolute).netloc):
            continue
        if re.search(r"career|job", href, re.I):
            rank = 3
        elif re.search(r"career|job", text, re.I):
            rank = 2
        else:
            rank = 1
        link_host = urlparse(absolute).netloc
        if link_host and host and link_host != host:
            rank += 1
        if rank > best_rank:
            best_rank, best = rank, absolute
    return best


_ATS_CAREERS_HOSTS = re.compile(
    r"(\.jobs(/|$)|amazon\.jobs|metacareers\.com|myworkdayjobs|wd\d\.myworkday|greenhouse\.io|"
    r"lever\.co|ashbyhq\.com|workable\.com|comeet\.com/jobs|smartrecruiters\.com)",
    re.I,
)


def is_careers_url(url: str) -> bool:
    """Whether a URL is a careers/jobs page rather than a bare homepage."""
    parsed = urlparse(url)
    host = parsed.netloc.casefold()
    if host.startswith(("jobs.", "careers.", "career.", "job.", "apply.", "boards.")):
        return True
    if _ATS_CAREERS_HOSTS.search(url):
        return True
    return bool(re.search(r"career|job|join|position|vacanc", f"{parsed.path}?{parsed.query}", re.I))


def _verified_target(name: str) -> tuple[Optional[str], Optional[str]]:
    """Resolve a verified-cache entry into a (careers_url, homepage) pair.

    A verified entry is trusted: any URL with a path or query is used directly as
    the careers page; only a bare domain root is crawled to find one.
    """
    entry = load_verified().get(name)
    if not entry:
        return None, None
    url = entry if entry.startswith("http") else f"https://{entry.lstrip('/')}"
    parsed = urlparse(url)
    if parsed.path.strip("/") or parsed.query or is_careers_url(url):
        return url, None
    return None, url


def find_careers_url(name: str, session: requests.Session) -> tuple[Optional[str], Optional[str]]:
    """Find a company's official careers page.

    Order: verified cache, automatic domain resolution, then a scripted web
    search fallback (so ambiguous names are searched instead of skipped).
    Returns a (careers_url, homepage_url) pair; both None when nothing is found.
    """
    careers, homepage = _verified_target(name)
    if careers:
        return careers, homepage
    if homepage is None:
        homepage = resolve_homepage(name, session)
    if not homepage:
        from linkedin_match.search import search_company

        found = search_company(name, session)
        if found:
            if is_careers_url(found):
                return found, None
            homepage = found
    if not homepage:
        return None, None
    page = fetch_html(homepage, session, timeout=8)
    if page:
        homepage = page[0]
        link = careers_link_from_html(page[0], page[1])
        if link:
            return link, homepage
    base = homepage.rstrip("/")
    urls = [base + pattern for pattern in CAREERS_URL_PATTERNS]
    pool = ThreadPoolExecutor(max_workers=_DISCOVERY_FANOUT_WORKERS)
    try:
        futures = [pool.submit(fetch_html, url, session, 8) for url in urls]
        for url, future in zip(urls, futures):
            if future.result():
                return url, homepage
        return None, homepage
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
