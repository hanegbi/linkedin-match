"""Write ranked matches and unresolved companies to JSON/CSV/text files."""

import csv
import json
from pathlib import Path

from linkedin_match.models import Match

MATCHES_JSON = Path("data/matches.json")
MATCHES_CSV = Path("data/matches.csv")
NEEDS_SEARCH = Path("data/needs_search.txt")


def write_needs_search(cache: dict[str, dict], path: Path = NEEDS_SEARCH) -> tuple[Path, int]:
    """Write companies whose careers page could not be resolved automatically.

    These are candidates for a one-off web search; add the verified careers URL
    to verified_domains.json so the next scrape picks them up.

    Returns:
        The output path and the number of companies written.
    """
    unresolved = sorted(
        name
        for name, entry in cache.items()
        if entry.get("status") in {"skipped", "needs_manual"}
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(unresolved) + ("\n" if unresolved else ""), encoding="utf-8")
    return path, len(unresolved)


def write_matches_json(matches: list[Match], path: Path = MATCHES_JSON) -> Path:
    """Write ranked matches to a JSON file and return its path."""
    payload = [match.model_dump() for match in matches]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_matches_csv(matches: list[Match], path: Path = MATCHES_CSV) -> Path:
    """Write ranked matches to a flat CSV file and return its path."""
    fields = [
        "score",
        "raw_score",
        "company",
        "connections",
        "title",
        "location",
        "url",
        "matched_keywords",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for match in matches:
            contacts = "; ".join(
                f"{c.full_name} ({c.position})" if c.position else c.full_name
                for c in match.connections
            )
            writer.writerow(
                {
                    "score": match.score,
                    "raw_score": match.raw_score,
                    "company": match.company,
                    "connections": contacts,
                    "title": match.job.title,
                    "location": match.job.location or "",
                    "url": match.job.url or "",
                    "matched_keywords": ", ".join(match.matched_keywords),
                }
            )
    return path
