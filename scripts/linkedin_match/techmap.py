"""Load and index the public techmap job dataset, keyed by company."""

import csv
import io
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from linkedin_match.models import Company, Job

logger = logging.getLogger("linkedin_match.techmap")

RAW_BASE = "https://raw.githubusercontent.com/mluggy/techmap/main/jobs/{category}.csv"
CACHE_DIR = Path("data/techmap")
CATEGORIES = [
    "software",
    "devops",
    "data-science",
    "security",
    "frontend",
    "hardware",
    "product",
    "qa",
    "support",
    "design",
    "project-management",
    "business",
    "finance",
    "marketing",
    "sales",
    "hr",
    "legal",
    "admin",
    "procurement-operations",
]

_SUFFIXES = re.compile(
    r"\b(ltd|ltd\.|inc|inc\.|llc|group|technologies|technology|labs|systems|software|solutions|israel|the)\b",
    re.IGNORECASE,
)


def normalize_company(name: str) -> str:
    """Reduce a company name to a comparison key (lowercase, no suffixes/punct)."""
    lowered = _SUFFIXES.sub(" ", (name or "").casefold())
    return re.sub(r"[^a-z0-9]+", "", lowered)


_normalize = normalize_company


def download_category(category: str, session: requests.Session, force: bool = False) -> str:
    """Download one job-category CSV, caching it locally under data/techmap."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{category}.csv"
    if path.exists() and not force:
        return path.read_text(encoding="utf-8")
    response = session.get(RAW_BASE.format(category=category), timeout=30)
    response.raise_for_status()
    path.write_text(response.text, encoding="utf-8")
    return response.text


def _row_to_job(row: dict, function: str) -> Job:
    """Convert a techmap CSV row into a normalized Job."""
    url = (row.get("url") or "").split("?")[0] or None
    return Job(
        title=(row.get("title") or "").strip(),
        location=(row.get("city") or "").strip() or None,
        url=url,
        description="",
        department=function,
        employment_type=(row.get("level") or "").strip() or None,
        posted_at=(row.get("updated") or "").strip() or None,
    )


def _fetch_category(category: str, session: requests.Session, force: bool) -> tuple[str, str | None]:
    """Download one category, pairing it with its text (or None on failure)."""
    try:
        return category, download_category(category, session, force=force)
    except requests.RequestException as error:
        logger.warning("techmap %s failed: %s", category, error)
        return category, None


def load_jobs(
    session: requests.Session,
    categories: list[str] | None = None,
    force: bool = False,
) -> list[tuple[str, Job]]:
    """Load all techmap jobs as (company_name, Job) pairs across categories.

    Downloads every category concurrently — these are independent GETs to
    GitHub's raw CDN, so fetching them one at a time just sums up 19 round
    trips for no reason.
    """
    cats = categories or CATEGORIES
    with ThreadPoolExecutor(max_workers=len(cats)) as pool:
        texts = dict(pool.map(lambda c: _fetch_category(c, session, force), cats))
    pairs: list[tuple[str, Job]] = []
    for category in cats:
        text = texts.get(category)
        if text is None:
            continue
        reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
        for row in reader:
            company = (row.get("company") or "").strip()
            title = (row.get("title") or "").strip()
            if company and title:
                pairs.append((company, _row_to_job(row, category)))
    return pairs


def company_sizes(session: requests.Session, force: bool = False) -> dict[str, str]:
    """Return a normalized-company -> LinkedIn size code (xs/s/m/l/xl) map."""
    sizes: dict[str, str] = {}
    for category in CATEGORIES:
        try:
            text = download_category(category, session, force=force)
        except requests.RequestException:
            continue
        reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
        for row in reader:
            company = (row.get("company") or "").strip()
            size = (row.get("size") or "").strip()
            if company and size:
                sizes[_normalize(company)] = size
    return sizes


def index_by_company(pairs: list[tuple[str, Job]]) -> dict[str, list[Job]]:
    """Index techmap jobs by their normalized company-name key."""
    index: dict[str, list[Job]] = {}
    for company, job in pairs:
        index.setdefault(_normalize(company), []).append(job)
    return index


def _match_key(company: str, index: dict[str, list[Job]]) -> str | None:
    """Find the techmap company key best matching a connection's company name.

    Prefers an exact normalized match; only falls back to a prefix match when both
    names are long and overlap substantially, to avoid false positives like
    "Ada" matching "adaptive".
    """
    key = _normalize(company)
    if not key:
        return None
    if key in index:
        return key
    if len(key) < 5:
        return None
    candidates = [
        k
        for k in index
        if len(k) >= 5
        and (k.startswith(key) or key.startswith(k))
        and min(len(k), len(key)) / max(len(k), len(key)) >= 0.7
    ]
    return min(candidates, key=len) if candidates else None


def companies_with_jobs(
    companies: list[Company],
    session: requests.Session,
    force: bool = False,
) -> list[Company]:
    """Attach techmap job listings to each connection company by name match."""
    index = index_by_company(load_jobs(session, force=force))
    for company in companies:
        match = _match_key(company.name, index)
        if match:
            company.positions = list(index[match])
            company.source = "techmap"
            company.status = "ok"
        else:
            company.status = "needs_manual"
    return companies
