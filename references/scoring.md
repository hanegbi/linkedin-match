# Scoring reference

`matching.score_job` produces a raw score; `rank_matches` keeps only Israel/remote
jobs with a positive score, sorts them, and rescales so the best match is **100**
(`raw_score` preserved). All matching is whole-word and case-insensitive.

| Signal | Source field in `keywords.py` | Weight |
| --- | --- | --- |
| Target role appears in the job **title** | `TARGET_ROLES` | +50 each |
| Must-have skill anywhere in the posting | `MUST_HAVE_KEYWORDS` | +10 each, **capped at +50** total |
| Nice-to-have skill anywhere | `NICE_TO_HAVE_KEYWORDS` | +3 each, **capped at +15** total |
| Exclude term anywhere | `EXCLUDE_KEYWORDS` | −20 each |
| Job located in the selected city (`match --city`) | `CITY_ALIASES` | +25 (only if already scoring > 0) |
| Experience fit vs `USER_YEARS_EXPERIENCE` | `USER_YEARS_EXPERIENCE` | +5 if ≤ user, 0 at +1, −20 and steeper at +2 (7y+) |
| Over-senior title/level (principal, staff, director, VP…) | `OVERQUALIFIED_TITLE_TERMS` | −20 |

The `python`-in-title bonus was removed (it double-counted `python`, already a
must-have, and biased toward one language). The skill buckets are capped so a
keyword-stuffed description can't out-score the much stronger signal of your target
role appearing in the **title**. The score reflects *job fit only* — the
connections are surfaced per company in the results (grouped under their company
with the contacts shown once) but no longer affect the score.

## Title filtering (what gets cached/considered)

`TITLE_INCLUDE_KEYWORDS` and `TITLE_EXCLUDE_KEYWORDS` gate which jobs are kept at all:
a job's title must contain an include keyword and no exclude keyword. Tune these to
the user's target — e.g. add "data engineer" / "mlops" for an ML focus, or remove
"qa"/"automation" if they don't want those.

## Location filtering

`ISRAEL_LOCATION_TERMS` (English + Hebrew city names) and `REMOTE_TERMS` decide which
locations are kept. Jobs with an empty location are kept; an explicit non-Israeli,
non-remote location is dropped.

## Pinned companies

`PINNED_COMPANIES` in `keywords.py` lists companies to **always include**, even when
their open roles score 0 against the CV — for places where the contacts alone make
them worth a look. Pinned jobs still must pass the title and location filters; they
just bypass the `score > 0` requirement (and show with a low normalized score).

### Selecting a city

`python app.py match --city "tel aviv"` boosts jobs in that city by +25 (a non-
destructive preference — jobs elsewhere are still ranked and shown). City names
resolve through `CITY_ALIASES` in `keywords.py`, which maps a canonical city to its
English/Hebrew/abbreviation spellings (e.g. "tel aviv" also matches `תל אביב`, `tlv`).
Add a city there if one is missing.

## Tips

- Edit one field at a time and re-run `python app.py match` to see the effect — it is
  instant (no re-download).
- If too few results: loosen `TITLE_INCLUDE_KEYWORDS` or lower `USER_YEARS_EXPERIENCE`.
- If too noisy: tighten `TITLE_EXCLUDE_KEYWORDS` or raise must-have specificity.
