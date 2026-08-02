# Title catalog refresh (LLM matching)

How the market-titles catalog gets rebuilt from a fresh scrape — by Sonnet
subagents semantically matching raw titles, not a string-canonicalization regex.

## Why LLM matching instead of string rules

A regex pass (stripping "Senior"/"Staff", splitting on commas, trimming a
trailing "II") catches punctuation and seniority variants, but misses semantic
equivalents ("Software Development Engineer" vs "SWE" vs "Software Engineer")
and lets scraper navigation text slip through as if it were a title (a real
run left `"careers"` in the catalog at 108 occurrences — a regex noise-word
list will always be one phrase behind the next site's markup). Sonnet, given
the existing catalog as a reference set, gets both right in one pass.

## When to run this

This is a maintenance/refresh operation, not part of the default `hybrid`/
`match`/report flow — running it costs one Sonnet subagent per batch. Run it
after a scrape has meaningfully changed (many new companies, or the catalog
feels stale), not on every scrape.

## The flow

```
Title catalog refresh:
- [ ] 1. Split raw titles into batches   (split_title_batches.py)
- [ ] 2. Match each batch with Sonnet     (subagents)
- [ ] 3. Merge into market_titles.json    (merge_title_batches.py)
```

**Step 1 — Split.** From `WORKDIR` (after `app.py hybrid` has populated
`data/jobs_cache.json`):
```
.venv/Scripts/python.exe "$SKILL/scripts/split_title_batches.py"
```
Prints `{raw_titles, batches, sizes, existing_catalog}`. `existing_catalog` is
the full list of ~500 titles already in the catalog — every batch's prompt needs
this so Sonnet matches against real existing entries instead of inventing near-
duplicates.

**Step 2 — Match with Sonnet subagents.** For each `data/title_batch_<i>.json`
(a JSON array of `{id, title, count}`), dispatch an **Agent with `model: sonnet`**
carrying the prompt below, substituting `{existing_catalog}` (from step 1's
output, as a JSON array of strings) and the batch. Run all batches in parallel in
one message (not one Agent call per message — see the report-scoring flow for
why that matters for actual concurrency). Each subagent writes
`data/title_out_<i>.json` — a JSON array of `{id, match}` only.

> You are matching raw job titles scraped from career pages against an existing
> catalog of canonical role titles, so equivalent titles aggregate together.
>
> Existing catalog (match against these verbatim when one fits):
> {existing_catalog}
>
> For each raw title below, decide:
> - If it means the same role as one of the existing catalog titles (including
>   synonyms, abbreviations, and different phrasing — e.g. "Software Development
>   Engineer" or "SWE" both mean "software engineer"), return that catalog title
>   **verbatim, exactly as written in the list above**.
> - If it's a real, distinct job title with no good match in the catalog, return
>   `"NEW:<short lowercase canonical form>"` (e.g. `"NEW:revenue operations
>   analyst"`) — strip seniority words and locations, keep it to the core role.
> - If it isn't a real job title at all — scraper navigation text like "Apply
>   Now", "Careers", "Learn More", "View all roles", a bare company/department
>   name, or gibberish — return `"NOISE"`.
>
> Return ONLY a JSON array, no prose, no markdown fence:
> `[{"id":"<id>","match":"<catalog title, NEW:..., or NOISE>"}]`
> Include every id from the input, in any order.
>
> Raw titles:
> {batch as JSON: [{"id","title","count"}]}

Keep batches independent so one malformed response can't sink the run; a batch
that fails JSON parsing is skipped by the merge step (its titles just don't get
folded in this run — no crash, no partial catalog corruption).

**Step 3 — Merge.**
```
.venv/Scripts/python.exe "$SKILL/scripts/merge_title_batches.py"
```
Matched titles' counts are added to the existing catalog entry. `NEW:` titles
are added only once their accumulated count across all batches clears
`--min-new-count` (default 3) — the same threshold the catalog was originally
built with, so one-off oddball titles don't bloat it. `NOISE` is dropped.
Catalog entries this run's scrape didn't touch keep their prior count rather
than being deleted (a partial re-scrape shouldn't erase roles from companies
not in this batch). Prints `{catalog_size, titles_matched_to_existing,
new_titles_added, batches_merged, batches_skipped}` and cleans up the scratch
`title_batch_*.json`/`title_out_*.json` files.

## Example (real output from a test run against actual scraped data)

Input batch (`title_batch_N.json`):
```json
[
  {"id": "t1",  "title": "Senior DevOps Engineer",              "count": 11},
  {"id": "t2",  "title": "CRM Dynamics Developer",               "count": 1},
  {"id": "t3",  "title": "AI Software Team Lead, ML Platform",   "count": 2},
  {"id": "t4",  "title": "AI Software Leader, ML Platform",      "count": 1},
  {"id": "t5",  "title": "AI Algorithms Tech Lead",               "count": 1},
  {"id": "t6",  "title": "Senior Fullstack Engineer",             "count": 3},
  {"id": "t7",  "title": "Anthropic Fellows Program, AI Safety",  "count": 1},
  {"id": "t8",  "title": "AI Bootcamp Course 3",                  "count": 1},
  {"id": "t9",  "title": "Careers",                              "count": 108},
  {"id": "t10", "title": "Learn More",                            "count": 30},
  {"id": "t11", "title": "Trabajar en Kiabi",                     "count": 1}
]
```

Sonnet's output (`title_out_N.json`):
```json
[
  {"id": "t1",  "match": "devops engineer"},
  {"id": "t2",  "match": "NEW:crm developer"},
  {"id": "t3",  "match": "NEW:ai software tech lead"},
  {"id": "t4",  "match": "NEW:ai software tech lead"},
  {"id": "t5",  "match": "NEW:ai algorithms tech lead"},
  {"id": "t6",  "match": "fullstack engineer"},
  {"id": "t7",  "match": "anthropic fellows program"},
  {"id": "t8",  "match": "NOISE"},
  {"id": "t9",  "match": "NOISE"},
  {"id": "t10", "match": "NOISE"},
  {"id": "t11", "match": "NOISE"}
]
```

What this shows:
- **t1** — straightforward match to an existing catalog entry (seniority stripped).
- **t2, t5** — genuinely new roles the catalog didn't have; each gets its own `NEW:` entry.
- **t3 + t4** — two *differently worded* titles for the same internal-ladder role
  collapse to the **same** `NEW:` entry (`ai software tech lead`), so their counts
  (2 + 1 = 3) merge instead of creating two near-duplicate catalog rows — this is
  the semantic-matching payoff a regex pass can't do.
- **t6, t7** — matches that need real judgment: "Fullstack" → the catalog's
  "fullstack engineer" spelling; a program name ("Anthropic Fellows Program")
  correctly treated as its own distinct role, not force-matched to "ai engineer".
- **t8** — "AI Bootcamp Course 3" is a training program, not a job — `NOISE`,
  something a keyword filter would likely miss since it contains "AI".
- **t9, t10, t11** — scraper navigation text, including non-English ("Trabajar en
  Kiabi" — Spanish for "Work at Kiabi"). `t9` had **108 occurrences**; a hardcoded
  noise-word list already had "careers" on it and *still* let this one through in
  a real run, because the noise-list check ran on the post-canonicalized text and
  missed this variant — this is why regex noise lists reliably fall one phrase
  behind the next site's markup, and semantic matching doesn't.

After merge, the catalog gains `ai software tech lead` (count 3, from t3+t4),
`ai algorithms tech lead` (count 1 — below the default `min-new-count=3`, so it
would **not** be added on its own; it'd need 2 more occurrences elsewhere in the
full run to clear the bar) and `crm developer` (count 1, same caveat). `t8-t11`
contribute nothing. `devops engineer`, `fullstack engineer`, and `anthropic
fellows program` get their counts incremented in the existing catalog.

## Cost shape

Title matching is much cheaper per-item than job-fit scoring (a title is a few
words, not a full description) — batches of 150 titles are reasonable. A market
of ~6,500 distinct raw titles is ~44 batches; run them in parallel, same as the
report flow's scoring batches.
