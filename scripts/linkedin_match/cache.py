"""Read/write the on-disk jobs cache and convert between Company and cache entries."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from linkedin_match.models import Company, Job

CACHE_PATH = Path("data/jobs_cache.json")


def load_cache(path: Path = CACHE_PATH) -> dict[str, dict]:
    """Load the jobs cache keyed by company name, or an empty dict if absent."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(data: dict[str, dict], path: Path = CACHE_PATH) -> None:
    """Atomically write the jobs cache to disk via a temp file and replace."""
    directory = path.parent if str(path.parent) else Path(".")
    handle, tmp_name = tempfile.mkstemp(dir=str(directory), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(data, out, indent=2, ensure_ascii=False)
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def company_to_entry(company: Company) -> dict:
    """Serialize a scraped Company into its cache entry shape."""
    return {
        "careers_url": company.careers_url,
        "source": company.source,
        "status": company.status,
        "scraped_at": company.scraped_at,
        "positions": [job.model_dump() for job in company.positions],
    }


def entry_to_company(name: str, entry: dict) -> Company:
    """Reconstruct a Company from its cache entry."""
    return Company(
        name=name,
        careers_url=entry.get("careers_url"),
        source=entry.get("source"),
        status=entry.get("status", "pending"),
        scraped_at=entry.get("scraped_at"),
        positions=[Job(**job) for job in entry.get("positions", [])],
    )


def scraped_today(entry: dict, now: datetime | None = None) -> bool:
    """Return whether a cache entry was scraped on the current UTC date."""
    stamp = entry.get("scraped_at")
    if not stamp:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    return when.date() == now.date()


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
