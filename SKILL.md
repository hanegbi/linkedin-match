---
name: linkedin-match
description: "Matches a job seeker to open roles at companies where they already have a LinkedIn contact (a warm intro), scores fit against their CV, and produces a ranked, contact-backed report — a fast keyword-matched CSV/JSON or a shareable AI-scored HTML page. Use whenever the user wants to job-hunt through their LinkedIn network, mentions a LinkedIn 'Connections.csv' export, asks to match their CV/resume against open jobs, wants to find warm intros at companies that are hiring, or wants a report of jobs they're a good fit for through people they know — even if they haven't uploaded the CSV or CV yet, since the skill asks for them. Covers any field: engineering, data, product, design, marketing, sales, and more."
compatibility: "Requires Python 3.13+ and internet access (to scrape job postings). Fully self-contained — no other repo needed. The AI-scored report flow dispatches Agent subagents with model:sonnet, so it needs Claude Code (or another client that supports subagents); the keyword flow works anywhere. Recovering a JS-rendered career page (references/render-recovery.md) additionally needs the Playwright MCP server — optional, only for that one troubleshooting path, never required for the main flow."
license: MIT. LICENSE.txt has complete terms.
metadata:
  version: "1.0.0"
  category: job-search
  tags: [linkedin, job-search, career, warm-intro, resume-matching]
---

# LinkedIn-Match

Match a job seeker to open jobs at companies where they have a contact. Jobs come
from the mluggy/techmap dataset plus career-page scraping; the connections supply
the contacts; the CV and target titles drive the scoring. This skill is fully
self-contained — it bundles its own copy of the matching engine in `scripts/`, so
it doesn't depend on any other project being cloned.

Two flows — pick by what the user asks for:

- **AI-scored HTML report** (default for "score my fit" or "a shareable page") —
  filter each company's jobs to the target titles, score every kept job for CV fit
  with **Sonnet subagents**, and write `<Name>-job-report.html`. Steps below.
- **Keyword match** (fast, no AI, CLI only) — deterministic scoring to
  `matches.json`/`matches.csv`. See [references/scoring.md](references/scoring.md).

## Setup

- `SKILL` = this skill's directory (holds `scripts/` and `references/`).
- `WORKDIR` = a folder the user picks for this job search (e.g. `~/job-search/`).
  This is where their CSV/CV live and where `data/` and the final HTML get written
  — keep personal job-search data out of the skill's own directory.
- One-time environment setup, run from `WORKDIR`:
  ```
  python -m venv .venv
  .venv/Scripts/python.exe -m pip install -r "$SKILL/scripts/requirements.txt"
  ```
  (On macOS/Linux the venv's python is at `.venv/bin/python` instead of
  `.venv/Scripts/python.exe` — use whichever exists.)
- Inputs live in `WORKDIR`: a `Connections.csv` export and a `.docx`/`.pdf`/`brief.txt` CV.
- All commands below run from `WORKDIR` using that venv's python, pointed at the
  scripts bundled in `$SKILL/scripts/`.

## AI-scored report flow

Only **one** step calls an LLM — the Sonnet scoring in step 6. Everything else is
native Python. Scoring is done **only** by the model this skill runs with (Claude
subagents); never call out to a third-party LLM API or require an API key. Rubric
and the exact scoring prompt: [references/report.md](references/report.md).

Copy this checklist and track progress:

```
Job report progress:
- [ ] 1. Collect inputs (CSV + CV file paths)
- [ ] 2. Confirm titles       (required gate — before any LLM)
- [ ] 3. Scrape jobs (skip if the cache is fresh) — app.py hybrid --all-jobs
- [ ] 4. Prep + filter        (report.py prep)
- [ ] 5. Split batches        (scripts/split_batches.py)
- [ ] 6. Score each batch     (Sonnet subagents)
- [ ] 7. Merge scores         (scripts/merge_scores.py)
- [ ] 8. Build the report     (report.py build)
```

**Step 1 — Collect inputs.** Ask with AskUserQuestion (two questions), each offering
"auto-discover in WORKDIR" or a typed path: the **Connections CSV**, then the
**CV/brief**. Keep both as file paths — `report.py` extracts the CV natively; never
paste CV text into the chat.

**Step 2 — Confirm titles (gate).** Never score until the user confirms titles.
This skill is domain-agnostic; infer the user's field from the CV. Load the market
catalog (a frozen const of ~500 real role families across all fields) and grep it
for their domain:
```
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,r'$SKILL/scripts'); from linkedin_match import market_titles as m; print('\n'.join(t for t in m.titles() if 'market' in t or 'growth' in t))"
```
Offer, via AskUserQuestion, a shortlist of **distinct** best-fit titles (not variants
of one) plus the user's own; "Other" lets them type any title, added as-is. Don't
ask a separate exclude-words question — leave `exclude_titles` empty; the report's
"Hide titles with…" box already lets the user exclude interactively after the fact,
so asking upfront is redundant friction. Titles are the only thing gated on
confirmation — they're what actually gets sent to the LLM, so a wrong pick wastes
real scoring calls. Draft a 1-2 sentence `blurb` and a ≤400-char `persona` (CV
summary; it keys the score cache) yourself and move straight on to scraping — don't
ask the user to confirm the blurb/persona text, that's just cache-key/display
copy, not a decision that needs a round trip. Weight the persona toward the
candidate's **most recent / current role** — that's the strongest signal of their
current level and direction, so it should anchor the summary rather than being
one bullet among many equally-weighted past jobs.

**Step 3 — Scrape** (skip if `data/jobs_cache.json` already exists and is recent):
`.venv/Scripts/python.exe "$SKILL/scripts/app.py" hybrid --all-jobs`.
This fills the one plain-JSON cache both flows read from — techmap dataset first,
then career-page scraping for whatever's left, stored in `data/jobs_cache.json`.
The `--all-jobs` flag matters: without it, jobs get pre-filtered to an
engineering-only title list (the keyword flow's own default — fine there, since
that flow's `keywords.py` is meant to be tuned per user anyway). The AI-report
flow does its own per-user title filtering in step 4, so this step needs to see
every field's jobs, not just engineering ones. Add `--force` to refresh stale data.

**Step 4 — Prep + filter.** Write `data/report_args.json` (`csv`/`cv` are paths, not text):
```json
{"candidate": "<Name>", "titles": ["backend engineer", "ai engineer"],
 "exclude_titles": [], "persona": "<=400-char CV summary>",
 "blurb": "<header blurb>", "csv": "<path or omit>", "cv": "<path or omit>",
 "out": "<Name>-job-report.html", "max": 400}
```
Run `.venv/Scripts/python.exe "$SKILL/scripts/report.py" prep`. It prints
`{companies, jobs, to_score, batches, cached}` and writes `data/score_batches.json`
+ `data/report_input.json`.

**Step 5 — Split batches.** `.venv/Scripts/python.exe "$SKILL/scripts/split_batches.py"`.
Writes one `data/score_batch_<i>.json` per batch and prints the persona + titles.
If `batches` was 0 (all cached), skip to step 8.

**Step 6 — Score with Sonnet subagents.** For each `data/score_batch_<i>.json`,
dispatch an **Agent with `model: sonnet`** carrying the scoring prompt from
[references/report.md](references/report.md), the persona/titles from step 5, and that
batch. Run several in parallel. Each subagent writes `data/score_out_<i>.json` — a
JSON array `[{"id","score","tag"}]` only.

**Step 7 — Merge scores.** `.venv/Scripts/python.exe "$SKILL/scripts/merge_scores.py"`.
Merges every `score_out_*.json` into `data/ai_scores.json` and cleans up the scratch files.

**Step 8 — Build the report.** `.venv/Scripts/python.exe "$SKILL/scripts/report.py" build`.
Folds the scores into the cache and writes `<Name>-job-report.html`: a titles+blurb hero,
contacts per company, AI fit badges, a multi-select location filter (cities + Remote;
picking any also shows N/A-location jobs), a "Hide titles with…" box, min-fit slider,
search, like / hide-job / hide-company, "Liked only", and Restore-all — all persisted
in the browser. Point the user at the file. Don't proactively ask about excludes or
more titles — the report's own filters handle excludes, and if the user wants more
roles they'll ask. If they do, don't guess from scores (unmatched titles were never
sent to the LLM) — see "Finding more titles" in
[references/report.md](references/report.md) for the frequency-based approach.

## Keyword flow

Deterministic CLI ranking, no AI. Tune `$SKILL/scripts/linkedin_match/keywords.py`
for the user's own role/skills (its shipped defaults are backend/AI-infra-oriented —
that's the fast path's starting point, not a hard limit), build the cache with
`.venv/Scripts/python.exe "$SKILL/scripts/app.py" hybrid`, then rank:
`.venv/Scripts/python.exe "$SKILL/scripts/app.py" match --limit 30` (writes
`matches.json`/`matches.csv`). Present results best-first as **company → contact(s)
→ job**. Field weights and title filtering: [references/scoring.md](references/scoring.md).

## Title catalog refresh (maintenance, optional)

The ~500-title catalog Step 2 offers is a frozen file, built once and shipped
with the skill — it doesn't grow from what later scrapes find. If the user wants
it refreshed against fresh market data (new companies scraped, or the catalog
feels stale/missing their field), Sonnet subagents match every raw scraped title
against the existing catalog — semantic matching, not a string-canonicalization
regex, so it catches synonyms a regex would miss and reliably drops scraper
navigation noise. Not part of the default flow; run it on request. Full steps
and the exact matching prompt: [references/title-catalog.md](references/title-catalog.md).

## Location catalog refresh (maintenance, optional)

Locations have the same problem titles did: `keywords.CITY_ALIASES` hand-lists
~23 known Israeli cities with their spelling/Hebrew variants, but a hardcoded
list is always one variant behind — real scrapes turn up misspellings ("Ranana"
for "Raanana"), Hebrew hyphenation the alias strings don't expect
("תל-אביב" vs "תל אביב"), and whole cities never added (Rishon LeZion isn't in
the table at all). If the user wants cleaner location labels in the report
(fewer jobs showing a blank city that's actually a known one under a variant),
Sonnet subagents resolve every raw location the alias table couldn't — most raw
locations are legitimately foreign and get skipped automatically, so this only
processes genuinely ambiguous ones. Full steps and the exact matching prompt:
[references/location-catalog.md](references/location-catalog.md). Locations are
resolved during **prep** (step 4), not build, so after running this, re-run
steps 4 and 8 (`report.py prep` then `report.py build`) to pick up cleaner
locations in the HTML — skip 5-7, since every job is already scored and the
score cache means prep costs nothing new.

## Notes

- Re-run `app.py hybrid --all-jobs` to refresh jobs; scores persist in
  `data/scores.json`, so re-running a candidate only pays for genuinely new postings.
- For a JS-only career page that yields no jobs, pin a URL in
  `$SKILL/scripts/verified_domains.json` (`"Company": "https://.../careers"`) and re-run.

## Troubleshooting

Common failures (missing venv, zero-job reports, malformed subagent output, JS-only
career pages) and their fixes: [references/troubleshooting.md](references/troubleshooting.md).
