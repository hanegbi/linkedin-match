"""Scrape a company's careers page and ATS provider for open positions."""

import html as html_module
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import linkedin_match.matching as matching
from linkedin_match.cache import company_to_entry, entry_to_company, scraped_today, utc_now_iso
from linkedin_match.companies import ATS_ORDER, COMPANY_OVERRIDES
from linkedin_match.discovery import domain_label, fetch_html, find_careers_url
from linkedin_match.fetchers import ATS_FETCHERS, make_session, parse_comeet_hosted
from linkedin_match.matching import title_is_relevant
from linkedin_match.models import Company, Job

logger = logging.getLogger("linkedin_match.scraper")

_JOB_LINK_HINT = re.compile(r"(job|position|career|opening|vacanc|gh_jid|lever\.co|greenhouse)", re.I)

_ATS_BOARD_URL = {
    "greenhouse": "https://boards.greenhouse.io/{token}",
    "lever": "https://jobs.lever.co/{token}",
    "ashby": "https://jobs.ashbyhq.com/{token}",
    "workable": "https://apply.workable.com/{token}/",
    "comeet": "https://www.comeet.com/jobs/{token}",
}

_EMBED_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board\?for=([A-Za-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"boards(?:-api)?\.greenhouse\.io/(?:v1/boards/)?([A-Za-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"(?:jobs|api)\.lever\.co/(?:v0/postings/)?([A-Za-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"accountName\s*[:=]\s*['\"]([A-Za-z0-9_-]+)['\"]", re.I)),
    ("ashby", re.compile(r"(?:jobs|api)\.ashbyhq\.com/(?:posting-api/job-board/)?([A-Za-z0-9_-]+)", re.I)),
    ("comeet", re.compile(r"comeet\.com/jobs(?:-api/[0-9.]+/company)?/([A-Za-z0-9_-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/([A-Za-z0-9_-]+)", re.I)),
    ("workable", re.compile(r"https?://([A-Za-z0-9_-]+)\.workable\.com", re.I)),
]


def slugify(name: str) -> str:
    """Reduce a company name to a lowercase alphanumeric ATS token."""
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def token_candidates(name: str) -> list[str]:
    """Generate ordered ATS-token guesses, keeping hyphenated variants.

    Many ATS accounts keep hyphens (e.g. "d-fendsolutions"), so a single
    alphanumeric slug is not enough; we also try spaces-removed and
    spaces-to-hyphen forms.
    """
    lower = name.casefold().strip()
    plain = re.sub(r"[^a-z0-9]", "", lower)
    no_space = re.sub(r"[^a-z0-9-]", "", lower.replace(" ", ""))
    hyphenated = re.sub(r"[^a-z0-9-]", "", re.sub(r"\s+", "-", lower))
    out: list[str] = []
    for token in (plain, no_space, hyphenated):
        token = token.strip("-")
        if token and token not in out:
            out.append(token)
    return out


def ats_board_url(source: str, token: str) -> Optional[str]:
    """Return the public board URL for an ATS source and token, if known."""
    template = _ATS_BOARD_URL.get(source)
    return template.format(token=token) if template else None


def _try_ats(source: str, token: str, session: requests.Session) -> Optional[list[Job]]:
    """Call one ATS fetcher under log-and-continue error handling."""
    try:
        return ATS_FETCHERS[source](session, token)
    except Exception as error:
        logger.debug("ATS %s/%s failed: %s", source, token, error)
        return None


_ATS_FANOUT_WORKERS = 6


def detect_ats(
    company: str,
    session: requests.Session,
    extra_tokens: Optional[list[str]] = None,
) -> tuple[Optional[str], Optional[str], Optional[list[Job]]]:
    """Probe known ATS providers for a company across token candidates.

    Prefers a board with open positions; an empty board (which often belongs to
    a different company sharing the token) is only used when nothing else hits.
    Checks every (source, token) combination concurrently rather than one at a
    time — a company that matches nothing was previously up to 5 providers x 3
    tokens = 15 *sequential* requests (each up to timeout x retries), which is
    the dominant cost for the worst-case companies. Returns as soon as a real
    hit is found, without waiting for the rest.

    Returns:
        A tuple of (source, token, jobs); all None when no board responds.
    """
    override = COMPANY_OVERRIDES.get(company)
    if override and override.get("source") in ATS_FETCHERS:
        token = override.get("token") or slugify(company)
        jobs = _try_ats(override["source"], token, session)
        if jobs:
            return override["source"], token, jobs

    tokens = token_candidates(company)
    for token in extra_tokens or []:
        if token and token not in tokens:
            tokens.append(token)
    combos = [(source, token) for source in ATS_ORDER for token in tokens]

    empty: Optional[tuple[str, str, list[Job]]] = None
    with ThreadPoolExecutor(max_workers=_ATS_FANOUT_WORKERS) as pool:
        futures = {pool.submit(_try_ats, source, token, session): (source, token) for source, token in combos}
        try:
            for future in as_completed(futures):
                source, token = futures[future]
                jobs = future.result()
                if jobs:
                    return source, token, jobs
                if jobs is not None and empty is None:
                    empty = (source, token, jobs)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    if empty is not None:
        return empty
    return None, None, None


def extract_embedded_ats(html: str) -> tuple[Optional[str], Optional[str]]:
    """Extract an ATS source and token embedded in a careers page's HTML."""
    for source, pattern in _EMBED_PATTERNS:
        match = pattern.search(html)
        if not match:
            continue
        token = match.group(1)
        if token.lower() in {"embed", "v1", "boards", "v0", "postings", "job"}:
            continue
        return source, token
    return None, None


_GENERIC_LINK_TEXT = {
    "view role", "view position", "view job", "view opening", "view details",
    "apply", "apply now", "learn more", "read more", "see more", "see details",
    "details", "open position", "open role",
}
_TITLE_TAG = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_TITLE_FANOUT_WORKERS = 8
_TITLE_FANOUT_CAP = 30


def _clean_page_title(raw: str, company_hint: str) -> Optional[str]:
    """Extract a job title from a linked page's <title> tag.

    Strips only a trailing "| CompanyName" / "- CompanyName" suffix that matches
    the actual company name — never a bare split on the first separator, which
    would mangle real titles like "Senior Backend Engineer - Python".
    """
    m = _TITLE_TAG.search(raw)
    if not m:
        return None
    text = html_module.unescape(m.group(1)).strip()
    if company_hint:
        text = re.sub(r"\s*[|–—-]\s*" + re.escape(company_hint) + r"\s*$", "", text, flags=re.I).strip()
    return text or None


def _backfill_generic_titles(jobs: list[Job], session: requests.Session, company: str) -> None:
    """Follow links whose anchor text is a generic CTA and title them from the linked page.

    Many career pages (client-side rendered lists, e.g. Next.js sites) only expose
    "View Role"/"Apply now" as static anchor text; the real title lives in the linked
    page's own <title> tag. Bounded and concurrent so one slow/odd page can't stall
    the whole scrape.
    """
    targets = [j for j in jobs if j.url and j.title.strip().casefold() in _GENERIC_LINK_TEXT][:_TITLE_FANOUT_CAP]
    if not targets:
        return
    with ThreadPoolExecutor(max_workers=_TITLE_FANOUT_WORKERS) as pool:
        futures = {pool.submit(fetch_html, j.url, session, 8): j for j in targets}
        for future in as_completed(futures):
            job = futures[future]
            page = future.result()
            if not page:
                continue
            title = _clean_page_title(page[1], company)
            if title and title.casefold() != company.casefold():
                job.title = title


_MIN_TITLE_LEN = 9
_COUNT_BADGE = re.compile(r"\(\s*\d+\s*\)\s*$")
_SKIP_LINK = re.compile(r"^skip\b", re.I)
_LOGIN_LINK = re.compile(r"\b(log\s*in|log\s*back\s*in|sign\s*in)\b", re.I)
_SOCIAL_ICON = re.compile(r"\b(facebook|instagram|twitter|linkedin|youtube|tiktok)\s+(social\s+)?icon\b", re.I)


def _looks_like_chrome_text(title: str) -> bool:
    """Reject generic career-page UI chrome that isn't an individual posting.

    Filter/category badges ("All Jobs (227)"), accessibility skip-links, login CTAs,
    and social-media icon links are common, recurring patterns across many corporate
    career portals — not company-specific — and none are caught by the nav/header/
    footer or length checks alone.
    """
    return bool(
        _COUNT_BADGE.search(title)
        or _SKIP_LINK.match(title)
        or _LOGIN_LINK.search(title)
        or _SOCIAL_ICON.search(title)
    )


def _in_site_chrome(anchor) -> bool:
    """Whether an anchor sits inside <nav>/<header>/<footer> — site-wide chrome, not content.

    Matters most for rendered pages (fully-loaded DOM includes the whole site's nav,
    not just the careers section), where a "Sign in" or "Careers" nav link matches the
    loose job-link regex just as easily as a real posting.
    """
    return anchor.find_parent(["nav", "header", "footer"]) is not None


def parse_job_links(base_url: str, html: str, session: Optional[requests.Session] = None,
                     company: str = "") -> list[Job]:
    """Parse a careers page for job links as a best-effort fallback.

    Excludes links back to the careers page itself and anything sitting in site-wide
    nav/header/footer chrome (nav links match the loose job-link regex just as easily
    as real postings — a "Sign in" or "עברית" language switcher is not a job). When
    ``session`` is given, generic anchor text ("View Role" etc.) is backfilled from
    each linked page's title. A final short-title filter (language-agnostic, unlike a
    denylist) drops whatever chrome text still slips through either check.
    """
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    base_norm = base_url.rstrip("/")
    jobs: list[Job] = []
    for anchor in soup.find_all("a", href=True):
        if _in_site_chrome(anchor):
            continue
        href = anchor["href"]
        title = " ".join(anchor.get_text(separator=" ").split())
        if not title or len(title) < 3 or _looks_like_chrome_text(title):
            continue
        if not (_JOB_LINK_HINT.search(href) or _JOB_LINK_HINT.search(title)):
            continue
        absolute = urljoin(base_url, href)
        if absolute in seen or absolute.rstrip("/") == base_norm:
            continue
        seen.add(absolute)
        jobs.append(Job(title=title, url=absolute))
    if session is not None:
        _backfill_generic_titles(jobs, session, company)
    return [j for j in jobs if len(j.title) >= _MIN_TITLE_LEN and not _looks_like_chrome_text(j.title)]


def filter_titles(jobs: list[Job]) -> list[Job]:
    """Keep only CV-relevant job titles, unless title filtering is disabled."""
    if not matching.FILTER_TITLES:
        return jobs
    return [job for job in jobs if title_is_relevant(job.title)]


def _apply_ats_result(company: Company, source: str, token: str, jobs: list[Job]) -> None:
    """Record a successful ATS result, keeping the official careers URL."""
    company.source = source
    company.positions = filter_titles(jobs)
    company.status = "ok"
    if not company.careers_url:
        company.careers_url = ats_board_url(source, token)


def scrape_company(
    company: Company,
    session: requests.Session,
    known_careers_url: Optional[str] = None,
) -> Company:
    """Resolve a company's official careers page and open positions.

    Finds the careers page on the company's own website (skipping names too
    ambiguous to resolve), detects its ATS for jobs, and falls back to parsing
    the page. The careers URL is recorded even when no jobs are extracted.
    """
    company.scraped_at = utc_now_iso()
    homepage: Optional[str] = None
    if known_careers_url:
        company.careers_url = known_careers_url
    else:
        careers_url, homepage = find_careers_url(company.name, session)
        company.careers_url = careers_url

    if not company.careers_url and homepage is None:
        company.status = "skipped"
        return company

    reference = company.careers_url or homepage or ""
    extra = [domain_label(reference)] if reference else []
    source, token, jobs = detect_ats(company.name, session, extra)
    if jobs:
        _apply_ats_result(company, source, token, jobs)
        return company

    if company.careers_url:
        page = fetch_html(company.careers_url, session)
        if page:
            company.careers_url = page[0]
            if "comeet.com/jobs/" in company.careers_url.lower():
                hosted = parse_comeet_hosted(page[1])
                if hosted:
                    company.source = "comeet"
                    company.positions = filter_titles(hosted)
                    company.status = "ok"
                    return company
            embed_source, embed_token = extract_embedded_ats(page[1])
            if embed_source:
                embed_jobs = _try_ats(embed_source, embed_token, session)
                if embed_jobs:
                    _apply_ats_result(company, embed_source, embed_token, embed_jobs)
                    return company
            page_jobs = parse_job_links(page[0], page[1], session, company.name)
            if page_jobs:
                company.source = "careers"
                company.positions = filter_titles(page_jobs)
                company.status = "ok"
                return company

    company.source = None
    company.positions = []
    company.status = "needs_manual" if company.careers_url else "skipped"
    return company


def _scrape_safe(company: Company, session: requests.Session, known_careers_url: Optional[str]) -> Company:
    """Run scrape_company under log-and-continue error handling."""
    try:
        return scrape_company(company, session, known_careers_url)
    except Exception as error:
        logger.warning("scrape failed for %s: %s", company.name, error)
        company.status = "error"
        company.scraped_at = utc_now_iso()
        return company


def scrape_companies(
    companies: list[Company],
    cache: dict[str, dict],
    workers: int = 8,
    force: bool = False,
    retry: bool = False,
) -> dict[str, dict]:
    """Scrape companies concurrently, reusing same-day cache unless forced.

    A previously resolved careers URL is reused from the cache so the website
    discovery is not repeated on every run.

    Args:
        companies: Companies (with connections) to scrape jobs for.
        cache: Existing jobs cache keyed by company name.
        workers: Thread pool size.
        force: Re-scrape even if cached today.
        retry: Re-process only companies left unresolved (skipped/error/missing),
            engaging the web-search fallback for them.

    Returns:
        The updated cache dict keyed by company name.
    """
    if retry:
        pending = [c for c in companies if cache.get(c.name, {}).get("status") not in {"ok", "needs_manual"}]
    else:
        pending = [c for c in companies if force or not scraped_today(cache.get(c.name, {}))]
    session = make_session(pool_size=max(32, workers))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(_scrape_safe, company, session, cache.get(company.name, {}).get("careers_url")): company
            for company in pending
        }
        for future in as_completed(futures):
            done = future.result()
            cache[done.name] = company_to_entry(done)
            logger.info("%s -> %s (%s jobs)", done.name, done.status, len(done.positions))
    return cache


def companies_from_cache(companies: list[Company], cache: dict[str, dict]) -> list[Company]:
    """Merge cached job entries back onto companies that carry my connections."""
    merged: list[Company] = []
    for company in companies:
        entry = cache.get(company.name)
        if entry:
            cached = entry_to_company(company.name, entry)
            cached.connections = company.connections
            merged.append(cached)
        else:
            merged.append(company)
    return merged
