"""Split scraped job locations not already resolved into batches for Sonnet.

Reads every distinct job location out of ``data/jobs_cache.json``, drops any that
the hardcoded ``CITY_ALIASES``/remote regex already resolve OR that are already
decided in the persistent ``data/city_matches.json`` cache, and writes
``data/location_batch_<i>.json`` — each a JSON array of ``{id, location, count}``
— so each Sonnet matching subagent reads only its own batch. Prints a JSON line
with the batch count and the known-city list (the reference set each subagent
matches against).

Usage (run from the project root):
    python <skill>/scripts/split_location_batches.py                 # uses ./data
    python <skill>/scripts/split_location_batches.py --data DIR --batch-size 150
"""

import argparse
import json
import sys
from pathlib import Path

from linkedin_match import location_catalog as lc
from linkedin_match.keywords import CITY_ALIASES


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data", help="Project data directory (default: ./data)")
    parser.add_argument("--batch-size", type=int, default=150, help="Locations per batch (default: 150)")
    args = parser.parse_args()
    data = Path(args.data)

    cache_path = data / "jobs_cache.json"
    raw = lc.collect_raw_locations(cache_path)
    if not raw:
        sys.exit(f"No locations found in {cache_path} — run `app.py hybrid` first.")

    ambiguous = lc.needs_llm_check(raw)
    match_cache = lc.load_city_match_cache(data / "city_matches.json")
    unmatched = lc.unmatched_locations(ambiguous, match_cache)
    batches = lc.prepare_location_batches(unmatched, batch_size=args.batch_size)

    for old in data.glob("location_batch_*.json"):
        old.unlink()
    for i, batch in enumerate(batches):
        (data / f"location_batch_{i}.json").write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "raw_locations": len(raw),
        "already_resolved_by_alias_table": len(raw) - len(ambiguous),
        "already_cached": len(ambiguous) - len(unmatched),
        "to_classify": len(unmatched),
        "batches": len(batches),
        "sizes": [len(b) for b in batches],
        "known_cities": sorted(CITY_ALIASES.keys()),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
