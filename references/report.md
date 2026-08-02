# AI-scored report reference

How the report flow scores jobs and stays cheap.

## Titles: the catalog + the confirmation gate

The real menu of titles lives in `scripts/linkedin_match/market_titles.json` — a
frozen catalog of ~500 aggregated role families across every field, shipped with
the skill. Load it with `market_titles.titles()`. Use it to propose a title
checklist to the user and to
map their stated titles onto real ones. **Always confirm titles with the user
(yes/no + manual additions) before scoring** — scoring is the only paid step and
the titles decide what gets scored. `exclude_titles` (free text, whole-word) drops
matching jobs before the gate.

## What reaches the LLM (the token budget)

`report.py prep` keeps a job only if **all** hold: its title matches one of the
target titles (whole-word), its title contains none of the `exclude_titles`, it is
in Israel or remote, and it is not scraper-noise text. It then splits the survivors into jobs already in the score cache (reused for
free) and jobs still needing a score. The uncached set is ranked by deterministic
keyword fit and capped at `max` (default 400), deduped so identical postings across
companies score once. Only that capped, deduped set is batched for Sonnet — so cost
tracks the *relevant* market, not the whole one. Descriptions are trimmed to 600
chars per job; a batch is 20 jobs.

Re-runs are cheap: scores persist to `data/scores.json` keyed by
`persona + titles + job title + description`, so scoring the same candidate again
only pays for genuinely new postings.

## The scoring prompt (give this to each Sonnet subagent)

Scoring is done **only** by the model this skill runs with — `model: sonnet`
subagents. The repo has no API-key scorer and this flow never uses an external API
key: the candidate's fit for each job is judged by the Claude subagents alone.

Dispatch one Agent per batch with `model: sonnet`. Substitute `{persona}`,
`{titles}`, and the batch's jobs. The subagent must return JSON only.

> You are a technical recruiter scoring how well ONE candidate fits each job.
>
> Candidate persona: "{persona}"
> Target titles: {titles}
>
> For each job below, rate 1-100 how well THIS candidate fits it:
> 100 = ideal match, 75+ = strong, 50-74 = plausible, <50 = weak/stretch, <25 = poor.
> Judge on required skills, domain, and seniority vs the persona — NOT company
> prestige or how nicely the post is written. A wrong seniority (too junior or too
> senior for the candidate) caps the score below 55.
>
> Return ONLY a JSON array, no prose, no markdown fence:
> `[{"id":"<id>","score":<int>,"tag":"strong|ok|stretch"}]`
> tag: "strong" if score≥75, "ok" if 50-74, "stretch" if <50. Include every id.
>
> Jobs:
> {batch as JSON: [{"id","title","desc"}]}

Keep the batches independent so they parallelize and one bad batch can't sink the
run. If a subagent returns malformed JSON, re-ask that one batch once; if it still
fails, skip it — those jobs render with a neutral "—" badge.

## Merge + build

`scripts/merge_scores.py` merges every `data/score_out_<i>.json` the subagents
wrote into `data/ai_scores.json` as `{id: {score, tag}}`. Then `report.py build`:
- resolves each shown job's score from the cache first, else the LLM (a job
  inherits the score of the representative id sharing its cache key),
- persists the fresh LLM scores to `data/scores.json`,
- renders `<Name>-job-report.html`: a hero with the target titles + blurb, then
  companies ranked by their best-fit job, each showing the contacts there and the
  jobs with fit badges.

## Tuning

- Too many jobs / too costly → lower `max`, or narrow the target titles.
- Too few jobs → broaden titles, or check the scrape actually returned roles
  (`app.py hybrid` output). The title filter is whole-word on the job title only.
- Scores look off → tighten the `persona` (it is the single biggest lever; make it
  concrete about stack, domain, and years) and re-run `build` after clearing the
  cache for that candidate if needed.

## Finding more titles at the same companies (only if the user asks)

If the user asks for more roles after seeing the report, don't guess — the signal
isn't a score (jobs outside the original titles were never sent to the LLM), it's
**frequency at the companies already in the report**: those are companies with a
confirmed contact where at least one title already matched, so their *other* open
roles are a warm, relevant place to look.

```
.venv/Scripts/python.exe -c "
import sys, json
sys.path.insert(0, r'$SKILL/scripts')
from collections import Counter
from linkedin_match.textmatch import canonical_title, is_noise_title
report = json.load(open('data/report_input.json', encoding='utf-8'))
cache = json.load(open('data/jobs_cache.json', encoding='utf-8'))
current = {t.lower() for t in report['titles']}
in_report = {c['company'] for c in report['companies']}
counts = Counter()
for name in in_report:
    for job in cache.get(name, {}).get('positions', []):
        role = canonical_title(job.get('title') or '')
        if role and role not in current and not is_noise_title(role):
            counts[role] += 1
for role, n in counts.most_common(15):
    print(f'{n:>3}  {role}')
"
```

Show the top results (or offer via AskUserQuestion if there are several plausible
ones) framed as "these companies you already have a warm intro at are also hiring
for…", not as a scored recommendation. If the user wants any added, append them to
`report_args.json`'s `titles` array and go back to prep (step 4) — cheap, since
already-scored jobs are served from `data/scores.json` for free, so only the
newly-matched jobs need fresh batches/scoring.
