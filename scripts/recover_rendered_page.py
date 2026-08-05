"""Fold a Claude-rendered career page (via the Playwright MCP tool) into jobs_cache.json.

Last-resort recovery for a company whose careers page needs real JS execution to
show its jobs (nothing in a plain HTTP GET) — see SKILL.md's "Recovering a
JS-rendered career page" section for the full Playwright MCP workflow this
script is the second half of. Claude captures the rendered HTML (and any
job-board iframe's own HTML) to a file; this script parses it with the same
job-link extraction and noise filtering the scraper's static-HTML path uses,
and writes any jobs found straight into the cache.

Usage (run from the project root):
    python <skill>/scripts/recover_rendered_page.py \
        --company "Bolt" --url "https://www.bolt.com/careers" --html-file rendered.html
    python <skill>/scripts/recover_rendered_page.py ... --data DIR
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from linkedin_match.cache import company_to_entry, load_cache, save_cache, utc_now_iso
from linkedin_match.fetchers import make_session
from linkedin_match.models import Company
from linkedin_match.scraper import (
    _try_ats,
    extract_embedded_ats,
    filter_titles,
    parse_job_links,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", required=True, help="Exact company name, matching the connections CSV.")
    parser.add_argument("--url", required=True, help="The URL the HTML was rendered from (for relative-link resolution).")
    parser.add_argument("--html-file", required=True, help="Path to the saved rendered HTML.")
    parser.add_argument("--data", default="data", help="Project data directory (default: ./data)")
    args = parser.parse_args()

    html = Path(args.html_file).read_text(encoding="utf-8")
    stripped = html.strip()
    if stripped.startswith('"') and stripped.endswith('"'):
        # browser_evaluate's `filename` option saves a JS string return value as its
        # own JSON-encoded form (quotes and all) rather than the raw text — unescape it.
        try:
            html = json.loads(stripped)
        except json.JSONDecodeError:
            pass
    session = make_session()

    company = Company(name=args.company, careers_url=args.url, scraped_at=utc_now_iso())
    embed_source, embed_token = extract_embedded_ats(html)
    if embed_source:
        embed_jobs = _try_ats(embed_source, embed_token, session)
        if embed_jobs:
            company.source = embed_source
            company.positions = filter_titles(embed_jobs)
            company.status = "ok"

    if company.status != "ok":
        jobs = parse_job_links(args.url, html, session, args.company)
        if jobs:
            company.source = "careers-rendered-mcp"
            company.positions = filter_titles(jobs)
            company.status = "ok"

    data_dir = Path(args.data)
    cache = load_cache(data_dir / "jobs_cache.json")
    if company.status == "ok":
        cache[args.company] = company_to_entry(company)
        save_cache(cache, data_dir / "jobs_cache.json")

    print(json.dumps({
        "company": args.company,
        "found": company.status == "ok",
        "source": company.source,
        "jobs": len(company.positions),
        "titles": [j.title for j in company.positions],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
