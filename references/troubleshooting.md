# Troubleshooting

**Error: `ModuleNotFoundError` when running any script.**
Cause: the venv either wasn't created, or `pip install -r requirements.txt` didn't
run (or ran into the wrong Python — a system Python instead of `WORKDIR/.venv`).
Solution: redo Setup from `WORKDIR`, and always invoke scripts with
`.venv/Scripts/python.exe` (or `.venv/bin/python`), never bare `python`.

**Report has few or zero jobs for a non-engineering field (marketing, design, HR…).**
Cause: `hybrid` was run without `--all-jobs`, so the shared cache only kept
engineering-sounding titles. Solution: re-run
`.venv/Scripts/python.exe "$SKILL/scripts/app.py" hybrid --all-jobs --force` and
redo step 4 onward. Confirm with the user that step 3 used `--all-jobs` before
assuming their field genuinely has no open roles.

**`report.py prep` reports 0 companies.**
Cause: no LinkedIn contacts matched a scraped/cached company name (or the CSV
wasn't found — check it's the actual "Connections.csv" export, not a different
CSV). Solution: verify `report_args.json`'s `csv` path points at a real LinkedIn
export with a `Company` column, and that step 3 actually ran successfully first.

**A specific company shows no jobs even though it's clearly hiring.**
Cause: its career page is JS-rendered client-side, so scraping can't see the
listings. Solution: pin the exact careers URL in `verified_domains.json` (see
Notes in SKILL.md) and re-run `hybrid --all-jobs --force`.

**Sonnet subagent scoring returns malformed or missing scores for a batch.**
Cause: the subagent didn't follow the exact JSON-array-only output format from
[report.md](report.md). Solution: re-dispatch just that batch, restating the
required output format explicitly in the prompt; don't let `merge_scores.py` run
until every batch has a valid `score_out_<i>.json`.

**Title catalog refresh: a matching subagent returns malformed output.**
Same fix as above — `merge_title_batches.py` skips a `title_out_<i>.json` that
fails to parse rather than failing the whole run (that batch's titles just don't
get folded in), but re-dispatching it restating the exact `[{"id","match"}]`
format from [title-catalog.md](title-catalog.md) is cheap and keeps the catalog
complete.
