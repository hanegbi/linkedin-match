"""Collect raw scraped locations and cache Sonnet's canonicalization of them.

``keywords.CITY_ALIASES`` is a hand-seeded list of ~23 known Israeli cities with
their spelling/Hebrew variants — useful, but the same brittleness as the old
title-canonicalization regex: it only knows the variants someone thought to add.
Real scrapes turn up spellings it misses ("Ranana" vs "Raanana"), hyphenation it
doesn't expect ("Ramat-Gan" vs "Ramat Gan"), and whole cities it never had
("Rishon LeZion"). This module is the deterministic, cheap half of fixing that
the same way the title catalog was fixed: collect every distinct raw location,
let Sonnet subagents decide what each one really is against the known-city list
(see ``references/location-catalog.md``), and cache the answer in
``data/city_matches.json`` so ``report_prep.clean_city`` can use it without
re-asking next time.
"""

import json
import os
import tempfile
from pathlib import Path

from linkedin_match.matching import canonical_city, is_remote_location

JOBS_CACHE_PATH = Path("data/jobs_cache.json")
CITY_MATCH_CACHE_PATH = Path("data/city_matches.json")


def collect_raw_locations(cache_path: Path = JOBS_CACHE_PATH) -> list[dict]:
    """Collect every distinct raw job location from the jobs cache, case-insensitive.

    Returns ``[{location, count}]`` — the first-seen casing of each distinct
    location string and how many postings had it (or a case variant of it).
    """
    if not cache_path.exists():
        return []
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for entry in cache.values():
        for job in entry.get("positions", []):
            loc = (job.get("location") or "").strip()
            if not loc:
                continue
            key = loc.casefold()
            counts[key] = counts.get(key, 0) + 1
            display.setdefault(key, loc)
    return [{"location": display[k], "count": n} for k, n in counts.items()]


def needs_llm_check(raw_locations: list[dict]) -> list[dict]:
    """Drop locations the hardcoded ``CITY_ALIASES``/remote regex already resolve.

    No point spending an LLM call re-confirming "Tel Aviv" -> Tel Aviv; only the
    genuinely ambiguous remainder (misspellings, unlisted cities, foreign cities
    that need a real decision) goes to Sonnet.
    """
    return [
        r for r in raw_locations
        if not is_remote_location(r["location"]) and not canonical_city(r["location"])
    ]


def prepare_location_batches(raw_locations: list[dict], batch_size: int = 150) -> list[list[dict]]:
    """Assign a stable id to each raw location and split into fixed-size batches."""
    entries = [
        {"id": f"l{i}", "location": r["location"], "count": r["count"]}
        for i, r in enumerate(raw_locations)
    ]
    return [entries[i:i + batch_size] for i in range(0, len(entries), batch_size)]


def load_city_match_cache(path: Path = CITY_MATCH_CACHE_PATH) -> dict[str, str]:
    """Load the persistent raw-location -> canonical decision cache, or {} if none yet.

    Keyed by casefolded raw location; value is one of a known city name (title
    case, matching ``keywords.CITY_ALIASES`` keys), ``"REMOTE"``, or
    ``"NOT-ISRAEL"``.
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_city_match_cache(cache: dict[str, str], path: Path = CITY_MATCH_CACHE_PATH) -> None:
    """Atomically write the raw-location -> decision cache via a temp file and replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(cache, out, ensure_ascii=False)
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def unmatched_locations(raw_locations: list[dict], match_cache: dict[str, str]) -> list[dict]:
    """Filter raw locations down to ones not already decided in the match cache."""
    return [r for r in raw_locations if r["location"].casefold() not in match_cache]
