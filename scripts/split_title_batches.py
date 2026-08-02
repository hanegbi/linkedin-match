"""Split scraped job titles not already classified into batches for Sonnet.

Reads every distinct job title out of ``data/jobs_cache.json`` (case-insensitive,
with occurrence counts), drops any title already decided in the persistent
``data/title_matches.json`` cache (so a repeat refresh doesn't re-pay for titles
it already has an answer for), and writes ``data/title_batch_<i>.json`` — each a
JSON array of ``{id, title, count}`` — so each Sonnet matching subagent reads
only its own batch. Prints a JSON line with the batch count and the existing
catalog (the reference list each subagent matches raw titles against).

Usage (run from the project root):
    python <skill>/scripts/split_title_batches.py                 # uses ./data
    python <skill>/scripts/split_title_batches.py --data DIR --batch-size 150
"""

import argparse
import json
import sys
from pathlib import Path

from linkedin_match import market_titles as m


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data", help="Project data directory (default: ./data)")
    parser.add_argument("--batch-size", type=int, default=150, help="Titles per batch (default: 150)")
    args = parser.parse_args()
    data = Path(args.data)

    cache_path = data / "jobs_cache.json"
    raw = m.collect_raw_titles(cache_path)
    if not raw:
        sys.exit(f"No titles found in {cache_path} — run `app.py hybrid` first.")

    match_cache = m.load_match_cache(data / "title_matches.json")
    unmatched = m.unmatched_titles(raw, match_cache)
    batches = m.prepare_title_batches(unmatched, batch_size=args.batch_size)

    for old in data.glob("title_batch_*.json"):
        old.unlink()
    for i, batch in enumerate(batches):
        (data / f"title_batch_{i}.json").write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "raw_titles": len(raw),
        "already_cached": len(raw) - len(unmatched),
        "to_classify": len(unmatched),
        "batches": len(batches),
        "sizes": [len(b) for b in batches],
        "existing_catalog": m.titles(),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
