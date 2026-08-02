"""Merge the subagents' per-batch score files into one ai_scores.json.

Reads every ``data/score_out_<i>.json`` (each a JSON array of
``{id, score, tag}`` written by a scoring subagent) and merges them into
``data/ai_scores.json`` as ``{id: {score, tag}}`` — the file ``report.py build``
folds into the cache. Cleans up the per-batch input/output files afterward.

Usage (run from the project root):
    python <skill>/scripts/merge_scores.py            # uses ./data
    python <skill>/scripts/merge_scores.py --data DIR
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data", help="Project data directory (default: ./data)")
    args = parser.parse_args()
    data = Path(args.data)

    outs = sorted(data.glob("score_out_*.json"))
    if not outs:
        sys.exit(f"No score_out_*.json in {data} — the scoring subagents have not written results yet.")

    merged: dict[str, dict] = {}
    skipped = 0
    for path in outs:
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            skipped += 1  # a malformed batch is skipped; those jobs get a neutral badge
            continue
        for item in items:
            jid = item.get("id")
            if jid is None:
                continue
            merged[jid] = {"score": int(item.get("score", 0)), "tag": item.get("tag", "")}

    (data / "ai_scores.json").write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")

    # Tidy the scratch files so a later run starts clean.
    for path in list(data.glob("score_batch_*.json")) + outs:
        path.unlink()

    print(json.dumps({"scores": len(merged), "batches_merged": len(outs) - skipped,
                      "batches_skipped": skipped}))


if __name__ == "__main__":
    main()
