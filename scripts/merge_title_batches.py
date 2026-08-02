"""Merge Sonnet's title-matching batches into an updated market_titles.json.

Reads every ``data/title_out_<i>.json`` (each a JSON array of ``{id, match}``
written by a matching subagent) alongside the ``data/title_batch_<i>.json`` files
that gave it its ``{id, title, count}`` inputs, and folds the matched counts into
the catalog:

- ``match`` equal to an existing catalog title (verbatim) adds that raw title's
  count to it.
- ``match`` of the form ``NEW:<title>`` is a candidate new role; it's added only
  if its accumulated count clears ``--min-new-count`` (default 3), matching how
  the catalog was originally built.
- ``match`` of ``NOISE`` (scraper navigation text, not a real title) is dropped.

Catalog entries this run didn't touch (e.g. a partial re-scrape) keep their prior
count rather than being dropped. Writes the updated ``market_titles.json`` and
cleans up the scratch batch/output files afterward.

Also updates ``data/title_matches.json``, the persistent raw-title -> match cache
``split_title_batches.py`` uses to skip titles already classified. Only *durable*
outcomes are cached — an existing-catalog match, a NEW role that cleared the
threshold, or NOISE. A NEW candidate that didn't clear the threshold this run is
deliberately left uncached, so it's re-sent next time and gets another chance to
accumulate enough count instead of being stuck in limbo forever.

Usage (run from the project root):
    python <skill>/scripts/merge_title_batches.py                    # uses ./data
    python <skill>/scripts/merge_title_batches.py --data DIR --min-new-count 3
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from linkedin_match import market_titles as m


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data", help="Project data directory (default: ./data)")
    parser.add_argument(
        "--min-new-count", type=int, default=3,
        help="Minimum accumulated count for a NEW role to be added (default: 3)",
    )
    args = parser.parse_args()
    data = Path(args.data)

    batch_files = sorted(data.glob("title_batch_*.json"))
    out_files = sorted(data.glob("title_out_*.json"))
    if not out_files:
        sys.exit(f"No title_out_*.json in {data} — the matching subagents have not written results yet.")

    id_lookup: dict[str, tuple[str, int]] = {}
    for path in batch_files:
        for entry in json.loads(path.read_text(encoding="utf-8")):
            id_lookup[entry["id"]] = (entry["title"], entry["count"])

    matched: Counter[str] = Counter()
    new_candidates: Counter[str] = Counter()
    title_decisions: dict[str, str] = {}  # raw title -> its match decision, for caching below
    skipped = 0
    for path in out_files:
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            skipped += 1  # a malformed batch is skipped, not fatal
            continue
        for item in items:
            tid = item.get("id")
            match = (item.get("match") or "").strip()
            if tid not in id_lookup or not match:
                continue
            title, count = id_lookup[tid]
            title_decisions[title] = match
            if match == "NOISE":
                continue
            if match.startswith("NEW:"):
                new_candidates[match[4:].strip().lower()] += count
            else:
                matched[match] += count

    rebuilt: dict[str, int] = dict(matched)
    new_added = 0
    cleared_new_roles: set[str] = set()
    for role, count in new_candidates.items():
        if count >= args.min_new_count:
            rebuilt[role] = rebuilt.get(role, 0) + count
            new_added += 1
            cleared_new_roles.add(role)
    for entry in m.load_catalog():
        rebuilt.setdefault(entry["title"], entry["count"])

    catalog = [{"title": t, "count": n} for t, n in sorted(rebuilt.items(), key=lambda x: -x[1])]
    m.CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=0), encoding="utf-8")

    # Persist only durable decisions: an existing-catalog match or NOISE is stable
    # forever; a NEW role that didn't clear the threshold this run is left
    # uncached so it's re-sent and gets another chance to accumulate count.
    match_cache = m.load_match_cache(data / "title_matches.json")
    newly_cached = 0
    for title, decision in title_decisions.items():
        if decision.startswith("NEW:") and decision[4:].strip().lower() not in cleared_new_roles:
            continue
        key = title.casefold()
        if key not in match_cache:
            newly_cached += 1
        match_cache[key] = decision
    m.save_match_cache(match_cache, data / "title_matches.json")

    for path in list(batch_files) + out_files:
        path.unlink()

    print(json.dumps({
        "catalog_size": len(catalog),
        "titles_matched_to_existing": len(matched),
        "new_titles_added": new_added,
        "titles_cached_for_reuse": newly_cached,
        "batches_merged": len(out_files) - skipped,
        "batches_skipped": skipped,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
