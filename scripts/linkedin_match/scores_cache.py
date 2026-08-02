"""JSON cache of LLM job scores, keyed by (persona + titles + job title + description).

Plain file, no database — a small personal tool like this doesn't need one. The
key hashes the description, so a changed description produces a new key and
misses the cache — a stale score is never served.
"""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCORES_PATH = Path("data/scores.json")


def _now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def titles_key(titles: list[str]) -> str:
    """Normalize target titles to an order-independent cache component."""
    return "|".join(sorted({t.strip().lower() for t in titles if t.strip()}))


def cache_key(tkey: str, job_title: str, description: str, persona: str = "") -> str:
    """Hash persona, titles key, job title, and description into a stable cache key.

    The persona (short CV summary) is part of the key so a personalized score is
    only reused for the same candidate profile + titles + job.
    """
    raw = f"{(persona or '').strip()}\x00{tkey}\x00{(job_title or '').strip()}\x00{(description or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load(path: Path | None = None) -> dict[str, dict]:
    """Load the scores cache dict, or {} if it doesn't exist yet."""
    p = path or SCORES_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict[str, dict], path: Path | None = None) -> None:
    """Atomically write the scores cache dict via a temp file and replace."""
    p = path or SCORES_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False)
        os.replace(tmp_name, p)
    except BaseException:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def get_cached(keys: list[str], path: Path | None = None) -> dict[str, dict]:
    """Return ``{cache_key: {"score", "reason"}}`` for the keys already scored."""
    if not keys:
        return {}
    data = _load(path)
    return {k: {"score": data[k]["score"], "reason": data[k].get("reason")} for k in keys if k in data}


def save(entries: list[dict], path: Path | None = None) -> None:
    """Upsert scored entries. Each entry needs cache_key, company, titles_key,
    score, reason, model."""
    if not entries:
        return
    data = _load(path)
    now = _now()
    for entry in entries:
        data[entry["cache_key"]] = {**entry, "created_at": now}
    _save(data, path)


def prune(ttl_days: int, path: Path | None = None) -> int:
    """Delete score entries older than ``ttl_days``; return how many were removed."""
    data = _load(path)
    if not data:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    kept = {k: v for k, v in data.items() if v.get("created_at", "") >= cutoff}
    removed = len(data) - len(kept)
    if removed:
        _save(kept, path)
    return removed


def clear(path: Path | None = None) -> int:
    """Delete every cached score; return how many entries were removed."""
    data = _load(path)
    removed = len(data)
    if removed:
        _save({}, path)
    return removed


def count(path: Path | None = None) -> int:
    """Return the number of cached scores."""
    return len(_load(path))
