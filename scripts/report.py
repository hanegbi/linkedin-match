"""CLI shim for the AI-scored job report — the two deterministic halves of the flow.

The Sonnet scoring in between is done by the job-match skill (Claude dispatching
subagents), not here. Usage:

    python report.py prep    # filter + cache-split + write data/score_batches.json
    python report.py build   # merge LLM scores + write <candidate>-job-report.html

Both read run parameters from ``data/report_args.json`` (written by the skill):
``{titles, persona, blurb, candidate, out, csv?, cv?, cv_text?, max?}``. ``csv``
and ``cv`` are file paths (auto-discovered in the project root if omitted); the CV
text is extracted natively so it never has to be pasted into the args. ``prep``
also prints a one-line JSON summary of how many jobs/batches need scoring.
"""

import json
import sys
from pathlib import Path

from linkedin_match import profile, report_html, report_prep
from linkedin_match.connections import find_connections_csv

ARGS_PATH = Path("data/report_args.json")
AI_SCORES_PATH = Path("data/ai_scores.json")


def _args() -> dict:
    return json.loads(ARGS_PATH.read_text(encoding="utf-8"))


def _cv_text(args: dict) -> str:
    """Resolve the CV text: explicit ``cv_text``, else extract from the ``cv`` path,
    else auto-discover a CV/brief in the project root. Empty string if none found."""
    if args.get("cv_text"):
        return args["cv_text"]
    path = Path(args["cv"]) if args.get("cv") else profile.find_cv()
    return profile.extract_cv_text(path) if path else ""


def _prep(args: dict) -> None:
    csv = Path(args["csv"]) if args.get("csv") else find_connections_csv()
    if not csv:
        raise SystemExit("No connections CSV found (set 'csv' in data/report_args.json).")
    summary = report_prep.prepare(
        csv, args["titles"], args["persona"], args["candidate"], args.get("blurb", ""),
        cv_text=_cv_text(args), exclude_titles=args.get("exclude_titles", []),
        max_jobs=int(args.get("max", report_prep.DEFAULT_MAX)),
    )
    print(json.dumps({**summary, "csv": str(csv)}))


def _build(args: dict) -> None:
    report_input = json.loads(report_prep.REPORT_INPUT.read_text(encoding="utf-8"))
    ai_scores = json.loads(AI_SCORES_PATH.read_text(encoding="utf-8")) if AI_SCORES_PATH.exists() else {}
    saved = report_prep.save_ai_scores(ai_scores, report_input)
    out = Path(args.get("out") or f"{args['candidate']}-job-report.html")
    report_html.write_report(report_input, ai_scores, out)
    print(json.dumps({"out": str(out), "cached_new": saved,
                      "companies": len(report_input["companies"])}))


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    args = _args()
    if cmd == "prep":
        _prep(args)
    elif cmd == "build":
        _build(args)
    else:
        raise SystemExit("usage: python report.py [prep|build]")


if __name__ == "__main__":
    main()
