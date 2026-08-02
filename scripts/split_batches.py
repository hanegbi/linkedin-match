"""Split the scoring batches into one small file per batch for the subagents.

Reads ``data/score_batches.json`` (written by ``report.py prep``) and writes
``data/score_batch_<i>.json`` — each a JSON array of ``{id, title, desc}`` — so
each Sonnet scoring subagent reads only its own batch. Prints a JSON line with the
persona, titles, and batch count so the caller can build the scoring prompt.

Usage (run from the project root):
    python <skill>/scripts/split_batches.py            # uses ./data
    python <skill>/scripts/split_batches.py --data DIR
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data", help="Project data directory (default: ./data)")
    args = parser.parse_args()

    src = Path(args.data) / "score_batches.json"
    if not src.exists():
        sys.exit(f"{src} not found — run `report.py prep` first.")
    payload = json.loads(src.read_text(encoding="utf-8"))
    batches = payload.get("batches", [])

    # Remove stale per-batch files from a previous run before writing fresh ones.
    for old in Path(args.data).glob("score_batch_*.json"):
        old.unlink()
    for i, batch in enumerate(batches):
        out = Path(args.data) / f"score_batch_{i}.json"
        out.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "batches": len(batches),
        "sizes": [len(b) for b in batches],
        "persona": payload.get("persona", ""),
        "titles": payload.get("titles", []),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
