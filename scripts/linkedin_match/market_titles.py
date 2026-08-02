"""Aggregated catalog of the distinct role titles present in the jobs market.

The market lists thousands of messy titles ("Senior Backend Engineer, Payments",
"Backend Engineer II", …) that collapse to a few hundred real roles. This skill
ships a pre-built, frozen catalog (``market_titles.json``, ~500 role families
across every field) so offering the user a menu of titles never needs a live
scrape or a database — it's a plain read-only JSON file bundled with the skill.

The catalog is refreshed by Sonnet subagents, not a regex heuristic: raw scraped
titles are matched against the existing catalog by an LLM (see
``references/title-catalog.md``), which handles synonyms and phrasing a
string-canonicalization pass would miss (e.g. "Software Development Engineer"
and "SWE" both matching "software engineer") and correctly drops scraper
navigation noise that isn't a real title at all. ``collect_raw_titles`` and
``prepare_title_batches`` (used by ``scripts/split_title_batches.py``) are the
deterministic, cheap half of that flow; the matching itself is not in this file.
"""

import json
import os
import tempfile
from pathlib import Path

CATALOG_PATH = Path(__file__).with_name("market_titles.json")
JOBS_CACHE_PATH = Path("data/jobs_cache.json")
MATCH_CACHE_PATH = Path("data/title_matches.json")

_cache: list[dict] | None = None


def load_catalog(path: Path = CATALOG_PATH) -> list[dict]:
    """Return the frozen ``[{title, count}]`` catalog (cached), or [] if not built."""
    global _cache
    if _cache is None:
        _cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    return _cache


def titles(path: Path = CATALOG_PATH) -> list[str]:
    """Just the catalogued role titles, most common first."""
    return [entry["title"] for entry in load_catalog(path)]


def collect_raw_titles(cache_path: Path = JOBS_CACHE_PATH) -> list[dict]:
    """Collect every distinct job title from the jobs cache, case-insensitive.

    Returns ``[{title, count}]`` — the first-seen casing of each distinct title
    and how many postings had it (or a case variant of it). No semantic
    canonicalization here; that's the LLM's job in the matching step.
    """
    if not cache_path.exists():
        return []
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for entry in cache.values():
        for job in entry.get("positions", []):
            title = (job.get("title") or "").strip()
            if not title:
                continue
            key = title.casefold()
            counts[key] = counts.get(key, 0) + 1
            display.setdefault(key, title)
    return [{"title": display[k], "count": n} for k, n in counts.items()]


def prepare_title_batches(raw_titles: list[dict], batch_size: int = 150) -> list[list[dict]]:
    """Assign a stable id to each raw title and split into fixed-size batches.

    Each entry becomes ``{id, title, count}``; the id lets the merge step match a
    subagent's response back to its title without relying on exact string
    round-tripping.
    """
    entries = [{"id": f"t{i}", "title": t["title"], "count": t["count"]} for i, t in enumerate(raw_titles)]
    return [entries[i:i + batch_size] for i in range(0, len(entries), batch_size)]


def load_match_cache(path: Path = MATCH_CACHE_PATH) -> dict[str, str]:
    """Load the persistent raw-title -> match cache, or {} if none yet.

    Keyed by casefolded raw title; value is what Sonnet decided last time (a
    catalog title, ``NEW:...``, or ``NOISE``). Without this, every catalog
    refresh would re-classify titles it already has an answer for — the same
    cost problem ``scores_cache`` solves for job scoring.
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_match_cache(cache: dict[str, str], path: Path = MATCH_CACHE_PATH) -> None:
    """Atomically write the raw-title -> match cache via a temp file and replace."""
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


def unmatched_titles(raw_titles: list[dict], match_cache: dict[str, str]) -> list[dict]:
    """Filter raw titles down to ones not already decided in the match cache."""
    return [t for t in raw_titles if t["title"].casefold() not in match_cache]
