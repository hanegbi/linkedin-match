"""Command-line entry point for the scrape, techmap, hybrid, match, and scores commands."""

import argparse
import logging
import sys
from pathlib import Path

from linkedin_match.cache import company_to_entry, load_cache, save_cache
from linkedin_match.connections import (
    find_connections_csv,
    group_by_company,
    load_connections,
    write_connections_json,
)
from linkedin_match.matching import rank_matches
from linkedin_match.models import Match
from linkedin_match.output import write_matches_csv, write_matches_json, write_needs_search
from linkedin_match.profile import build_profile, extract_cv_text, find_cv
from linkedin_match.scraper import companies_from_cache, scrape_companies


def _configure_output() -> None:
    """Force UTF-8 stdout/stderr and route progress logs to stderr."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
    )


def _resolve_csv(override: str | None) -> Path:
    """Resolve the connections CSV from an override or root auto-discovery."""
    if override:
        return Path(override)
    found = find_connections_csv()
    if not found:
        raise SystemExit("No connections CSV found in project root. Use --csv.")
    return found


def _resolve_cv(override: str | None) -> Path:
    """Resolve the CV file from an override or root auto-discovery."""
    if override:
        return Path(override)
    found = find_cv()
    if not found:
        raise SystemExit("No CV (.docx/.pdf) found in project root. Use --cv.")
    return found


def _apply_runtime_flags(args: argparse.Namespace, *, filter_titles: bool | None = None) -> None:
    """Apply CLI switches to the runtime flags in one place.

    Centralizes the ``search`` and ``matching`` module toggles so each command
    handler declares intent instead of repeating the assignments. ``filter_titles``
    overrides the ``--all-jobs`` default when a command needs a fixed value.
    """
    import linkedin_match.matching as matching
    import linkedin_match.search as search

    if hasattr(args, "no_search"):
        search.ENABLED = not args.no_search
    if filter_titles is not None:
        matching.FILTER_TITLES = filter_titles
    elif hasattr(args, "all_jobs"):
        matching.FILTER_TITLES = not args.all_jobs


def run_scrape(args: argparse.Namespace) -> None:
    """Scrape and cache jobs for every company found in the connections CSV."""
    _apply_runtime_flags(args)
    csv_path = _resolve_csv(args.csv)
    print(f"Reading connections from {csv_path}", file=sys.stderr)
    connections = load_connections(csv_path)
    _, unique = write_connections_json(connections)
    companies = group_by_company(connections)
    print(f"Found {unique} unique companies (wrote connections.json)", file=sys.stderr)
    cache = load_cache()
    cache = scrape_companies(
        companies, cache, workers=args.workers, force=args.force, retry=args.retry
    )
    save_cache(cache)
    ok = sum(1 for e in cache.values() if e.get("status") == "ok")
    _, unresolved = write_needs_search(cache)
    print(f"Cached {len(cache)} companies ({ok} ok). Saved jobs_cache.json", file=sys.stderr)
    if unresolved:
        print(
            f"{unresolved} companies need a manual careers URL -> see needs_search.txt, "
            f"add entries to verified_domains.json, then re-run with --force.",
            file=sys.stderr,
        )


def run_match(args: argparse.Namespace) -> None:
    """Build the profile from the CV and rank cached jobs against it."""
    csv_path = _resolve_csv(args.csv)
    cv_path = _resolve_cv(args.cv)
    print(f"Building profile from {cv_path}", file=sys.stderr)
    profile = build_profile(extract_cv_text(cv_path))
    companies = group_by_company(load_connections(csv_path))
    companies = companies_from_cache(companies, load_cache())
    if args.city:
        print(f"Boosting jobs in {args.city}", file=sys.stderr)
    matches = rank_matches(companies, profile, city=args.city)
    write_matches_json(matches)
    write_matches_csv(matches)
    print_matches(matches, limit=args.limit or 20)
    print(
        f"\nWrote {len(matches)} matches to matches.json and matches.csv",
        file=sys.stderr,
    )


def print_matches(matches: list[Match], limit: int) -> None:
    """Print top matches in company -> connection -> position shape."""
    if not matches:
        print("No positive matches. Run `python app.py scrape` first, or tune keywords.py.")
        return
    shown_intros = 6
    for rank, match in enumerate(matches[:limit], start=1):
        print(f"\n[{rank}] {match.company}  (score {match.score})")
        for contact in match.connections[:shown_intros]:
            role = f" — {contact.position}" if contact.position else ""
            print(f"    warm intro: {contact.full_name}{role}")
        extra = len(match.connections) - shown_intros
        if extra > 0:
            print(f"    warm intro: (+{extra} more)")
        location = f"  [{match.job.location}]" if match.job.location else ""
        print(f"    position: {match.job.title}{location}")
        if match.job.url:
            print(f"    url: {match.job.url}")
        if match.matched_keywords:
            print(f"    matched: {', '.join(match.matched_keywords)}")


def run_techmap(args: argparse.Namespace) -> None:
    """Build the jobs cache from the techmap dataset for the connection companies."""
    import linkedin_match.techmap as techmap
    from linkedin_match.fetchers import make_session

    _apply_runtime_flags(args)
    csv_path = _resolve_csv(args.csv)
    print(f"Reading connections from {csv_path}", file=sys.stderr)
    connections = load_connections(csv_path)
    _, unique = write_connections_json(connections)
    companies = group_by_company(connections)
    print(f"Found {unique} unique companies; loading techmap jobs…", file=sys.stderr)
    companies = techmap.companies_with_jobs(companies, make_session(), force=args.force)
    from linkedin_match.scraper import filter_titles

    cache = load_cache()
    ok = 0
    for company in companies:
        if company.status == "ok":
            company.positions = filter_titles(company.positions)
            ok += 1
        cache[company.name] = company_to_entry(company)
    save_cache(cache)
    total = sum(len(c.positions) for c in companies)
    print(f"Matched {ok}/{unique} companies to techmap, {total} jobs. Saved jobs_cache.json", file=sys.stderr)


def run_hybrid(args: argparse.Namespace) -> None:
    """Fill the cache from techmap, then scrape the unmatched real companies."""
    import linkedin_match.techmap as techmap
    from linkedin_match.companies import is_noise_company
    from linkedin_match.discovery import load_verified
    from linkedin_match.fetchers import make_session
    from linkedin_match.scraper import filter_titles

    _apply_runtime_flags(args)
    csv_path = _resolve_csv(args.csv)
    print(f"Reading connections from {csv_path}", file=sys.stderr)
    connections = load_connections(csv_path)
    _, unique = write_connections_json(connections)
    companies = group_by_company(connections)
    print(f"Found {unique} unique companies; matching techmap…", file=sys.stderr)

    session = make_session()
    companies = techmap.companies_with_jobs(companies, session, force=args.force)
    verified = load_verified()
    cache = load_cache()
    matched = 0
    to_scrape: list = []
    for company in companies:
        if company.name in verified:
            to_scrape.append(company)
        elif company.status == "ok":
            company.positions = filter_titles(company.positions)
            cache[company.name] = company_to_entry(company)
            matched += 1
        elif is_noise_company(company.name):
            company.status = "skipped"
            cache[company.name] = company_to_entry(company)
        else:
            to_scrape.append(company)

    print(f"Techmap matched {matched}; scraping {len(to_scrape)} unmatched companies…", file=sys.stderr)
    cache = scrape_companies(to_scrape, cache, workers=args.workers, force=args.force)
    save_cache(cache)
    ok = sum(1 for e in cache.values() if e.get("status") == "ok")
    _, unresolved = write_needs_search(cache)
    total = sum(len(e.get("positions", [])) for e in cache.values())
    print(
        f"Done: {ok} companies with jobs, {total} jobs cached "
        f"({matched} via techmap). {unresolved} still unresolved (needs_search.txt).",
        file=sys.stderr,
    )


def run_scores(args: argparse.Namespace) -> None:
    """Inspect or maintain the LLM score cache (data/scores.json)."""
    from linkedin_match import scores_cache
    from linkedin_match.config import get_settings

    if args.clear:
        removed = scores_cache.clear()
        print(f"Cleared {removed} cached scores.", file=sys.stderr)
    elif args.prune is not None:
        ttl = args.prune or get_settings().scores_ttl_days
        removed = scores_cache.prune(ttl)
        print(f"Pruned {removed} scores older than {ttl} days.", file=sys.stderr)
    print(f"{scores_cache.count()} scores cached.", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for the scrape and match commands."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--csv", help="Path to the connections CSV (default: auto-discover).")
    common.add_argument("--cv", help="Path to the CV file (default: auto-discover).")
    common.add_argument("--workers", type=int, default=8, help="Scrape thread pool size.")
    common.add_argument("--force", action="store_true", help="Re-scrape even if cached today.")
    common.add_argument(
        "--retry",
        action="store_true",
        help="Re-resolve only unresolved companies via web search.",
    )
    common.add_argument(
        "--no-search",
        action="store_true",
        help="Disable the live web-search fallback (use verified cache only).",
    )
    common.add_argument(
        "--all-jobs",
        action="store_true",
        help="Cache all job titles, not just CV-relevant ones.",
    )
    common.add_argument("--limit", type=int, help="Number of matches to print (default 20).")
    parser = argparse.ArgumentParser(prog="app.py", description="LinkedIn-Match CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scrape", parents=[common], help="Fetch and cache jobs for all companies.")
    sub.add_parser("techmap", parents=[common], help="Build the cache from the techmap dataset.")
    sub.add_parser("hybrid", parents=[common], help="Techmap jobs, then scrape unmatched companies.")
    match_parser = sub.add_parser(
        "match", parents=[common], help="Build profile, rank cached jobs, show results."
    )
    match_parser.add_argument(
        "--city",
        help='Boost jobs in this city, e.g. "tel aviv" or "herzliya" (others still shown).',
    )
    scores_parser = sub.add_parser(
        "scores", parents=[common], help="Inspect or maintain the LLM score cache (data/scores.json)."
    )
    scores_parser.add_argument(
        "--prune", type=int, nargs="?", const=0, metavar="DAYS",
        help="Delete scores older than DAYS (default: config scores_ttl_days).",
    )
    scores_parser.add_argument("--clear", action="store_true", help="Delete every cached score.")
    return parser


COMMANDS = {
    "scrape": run_scrape,
    "techmap": run_techmap,
    "hybrid": run_hybrid,
    "match": run_match,
    "scores": run_scores,
}


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and dispatch to the requested command via the registry."""
    _configure_output()
    args = build_parser().parse_args(argv)
    COMMANDS[args.command](args)
