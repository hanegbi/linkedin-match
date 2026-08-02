"""Merge Sonnet's location-matching batches into data/city_matches.json.

Reads every ``data/location_out_<i>.json`` (each a JSON array of
``{id, decision}`` written by a matching subagent) alongside the
``data/location_batch_<i>.json`` files that gave it its ``{id, location, count}``
inputs, and writes each raw location's decision into the persistent
``data/city_matches.json`` cache that ``report_prep.clean_city`` reads:

- A known city (title-case, e.g. ``"Tel Aviv"``) — the raw location is a
  misspelling/variant/unlisted-alias of it.
- ``"NEW:<city>"`` — a real Israeli city not yet in ``keywords.CITY_ALIASES``.
  Consider adding frequently-seen ``NEW:`` cities there permanently.
- ``"NOT-ISRAEL"`` — a genuine foreign location; correctly not a match.
- ``"REMOTE"`` — remote-indicating text the ``REMOTE_TERMS`` regex missed.

All four are durable decisions for that exact raw string, so (unlike the title
catalog's NEW-role threshold) everything gets cached — there's no count bar to
clear here. Cleans up the scratch batch/output files afterward.

Usage (run from the project root):
    python <skill>/scripts/merge_location_batches.py            # uses ./data
    python <skill>/scripts/merge_location_batches.py --data DIR
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from linkedin_match import location_catalog as lc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data", help="Project data directory (default: ./data)")
    args = parser.parse_args()
    data = Path(args.data)

    batch_files = sorted(data.glob("location_batch_*.json"))
    out_files = sorted(data.glob("location_out_*.json"))
    if not out_files:
        sys.exit(f"No location_out_*.json in {data} — the matching subagents have not written results yet.")

    id_lookup: dict[str, str] = {}
    for path in batch_files:
        for entry in json.loads(path.read_text(encoding="utf-8")):
            id_lookup[entry["id"]] = entry["location"]

    match_cache = lc.load_city_match_cache(data / "city_matches.json")
    tally: Counter[str] = Counter()
    newly_cached = 0
    skipped = 0
    for path in out_files:
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            skipped += 1  # a malformed batch is skipped, not fatal
            continue
        for item in items:
            lid = item.get("id")
            decision = (item.get("decision") or "").strip()
            if lid not in id_lookup or not decision:
                continue
            key = id_lookup[lid].casefold()
            if key not in match_cache:
                newly_cached += 1
            match_cache[key] = decision
            bucket = "NEW" if decision.startswith("NEW:") else decision
            tally[bucket] += 1

    lc.save_city_match_cache(match_cache, data / "city_matches.json")

    for path in list(batch_files) + out_files:
        path.unlink()

    print(json.dumps({
        "locations_cached_for_reuse": newly_cached,
        "matched_to_known_city": sum(v for k, v in tally.items() if k not in ("NEW", "NOT-ISRAEL", "REMOTE")),
        "new_cities_found": tally.get("NEW", 0),
        "not_israel": tally.get("NOT-ISRAEL", 0),
        "remote_caught": tally.get("REMOTE", 0),
        "batches_merged": len(out_files) - skipped,
        "batches_skipped": skipped,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
