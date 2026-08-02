# Location catalog refresh (LLM matching)

How ambiguous scraped job locations get resolved to a known Israeli city (or
correctly recognized as foreign/remote) — by Sonnet subagents, not a hardcoded
alias table alone.

## Why LLM matching instead of a bigger alias list

`keywords.CITY_ALIASES` hand-lists ~23 Israeli cities with known spelling and
Hebrew variants. It genuinely helps (`"Tel Aviv-Yafo"` already resolves to
`"Tel Aviv"` through it), but it's the same brittleness the title catalog had:
it only knows the variants someone thought to add. Real scrapes turn up
misspellings ("Ranana" for "Raanana"), hyphenation the alias strings don't
expect ("Ramat-Gan" vs "Ramat Gan"), and whole cities that were simply never
added (Rishon LeZion isn't in the table at all). A bigger hardcoded list is
always one variant behind the next posting; semantic matching isn't.

## Why most raw locations never need this

A real scrape's location list is dominated by genuinely foreign cities (Boston,
San Francisco, Singapore, London) that correctly don't match anything — that's
not a bug. `split_location_batches.py` only sends the LLM what the existing
`CITY_ALIASES`/remote regex couldn't already resolve, so a foreign-heavy scrape
doesn't waste calls re-confirming what's already working.

## When to run this

Maintenance/refresh, not part of the default flow — run it after a scrape, once,
before building a report if you want cleaner location labels (fewer jobs showing
a blank city that's actually a known Israeli city under a variant spelling).

## The flow

```
Location catalog refresh:
- [ ] 1. Split unresolved locations   (split_location_batches.py)
- [ ] 2. Match each batch with Sonnet  (subagents)
- [ ] 3. Merge into city_matches.json  (merge_location_batches.py)
```

**Step 1 — Split.** From `WORKDIR` (after `app.py hybrid` has populated
`data/jobs_cache.json`):
```
.venv/Scripts/python.exe "$SKILL/scripts/split_location_batches.py"
```
Prints `{raw_locations, already_resolved_by_alias_table, already_cached,
to_classify, batches, sizes, known_cities}`. `known_cities` is the current
`CITY_ALIASES` key list — the reference set each subagent matches against.

**Step 2 — Match with Sonnet subagents.** For each `data/location_batch_<i>.json`
(a JSON array of `{id, location, count}`), dispatch an **Agent with
`model: sonnet`** carrying the prompt below, substituting `{known_cities}` (from
step 1's output) and the batch. Run all batches in parallel in one message. Each
subagent writes `data/location_out_<i>.json` — a JSON array of `{id, decision}`
only.

> You are resolving raw job locations scraped from career pages to a known
> Israeli city, or correctly recognizing them as not one.
>
> Known Israeli cities (match against these; return the exact name as written):
> {known_cities}
>
> For each raw location below, decide:
> - If it's a misspelling, alternate transliteration, Hebrew name, or a known
>   city with extra text attached (district, country, a second city joined by
>   `|` or `,`), return the matching known city **exactly as written in the
>   list above** (e.g. "Ranana" and "Rananna" both mean "raanana"; "Tel
>   Aviv-Yafo, Tel Aviv District, Israel" means "tel aviv").
> - If it's a real Israeli city genuinely not in the known list (e.g. "Rishon
>   LeZion", "Ashdod", "Eilat"), return `"NEW:<city name, title case>"`.
> - If it's explicitly remote/hybrid text that isn't a location at all, return
>   `"REMOTE"`.
> - If it's a real location but not in Israel (any other country/city), return
>   `"NOT-ISRAEL"`.
>
> Return ONLY a JSON array, no prose, no markdown fence:
> `[{"id":"<id>","decision":"<known city, NEW:..., REMOTE, or NOT-ISRAEL>"}]`
> Include every id from the input, in any order.
>
> Raw locations:
> {batch as JSON: [{"id","location","count"}]}

**Step 3 — Merge.**
```
.venv/Scripts/python.exe "$SKILL/scripts/merge_location_batches.py"
```
Writes every decision into `data/city_matches.json` (raw location -> decision).
Unlike the title catalog, there's no count threshold here — every decision is
useful and gets cached immediately, since even a "NOT-ISRAEL" or "REMOTE"
answer saves re-asking about that exact string next time. Prints
`{locations_cached_for_reuse, matched_to_known_city, new_cities_found,
not_israel, remote_caught, batches_merged, batches_skipped}`.

`report_prep.clean_city` checks this cache automatically (after the hardcoded
`CITY_ALIASES`, before its last-resort regex strip) — no extra wiring needed
once the cache exists. If a `NEW:` city comes up often, consider adding it to
`keywords.CITY_ALIASES` permanently so it's resolved for free from then on.

## Example (a real batch, before this ran)

| Raw location | count | Decision |
|---|---|---|
| Ranana | 5 | `Raanana` |
| Rananna | 1 | `Raanana` |
| Ramat-Gan | 12 | `Ramat Gan` |
| Rishon Lezion | 8 | `NEW:Rishon LeZion` |
| Rishon LeZion, Israel | 3 | `NEW:Rishon LeZion` |
| Boston, Massachusetts, United States | 200 | `NOT-ISRAEL` |
| Remote-Friendly (Travel-Required) | 4 | `REMOTE` |

"Rishon Lezion" and "Rishon LeZion, Israel" — different raw strings — both
resolve to the same `NEW:Rishon LeZion`, so a later count-based promotion into
`CITY_ALIASES` would combine them correctly.
