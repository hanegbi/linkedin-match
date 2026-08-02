"""Prepare the AI-scored job report: filter, cache-split, and batch for Sonnet.

The report scores every job at a company where the candidate has a connection,
but only the jobs whose title matches the candidate's target titles. This module
does the deterministic, network-free half of that pipeline:

1. Group the connections into companies and attach their open jobs (from the
   JSON jobs cache via ``jobs.attach_jobs``).
2. Keep only jobs passing the title + Israel/remote-location + not-noise gate.
3. Compute each job's stable id and score-cache key; split into jobs already
   scored for this candidate (persona + titles) and jobs still needing the LLM.
4. Cap the to-be-scored set by deterministic keyword fit so a huge market stays
   bounded, then batch the survivors for the Sonnet subagents.

It writes two files: ``data/score_batches.json`` (what the LLM must score) and
``data/report_input.json`` (everything the HTML report needs, plus the ids that
were already cached). Scoring itself (Sonnet subagents) and rendering
(``report_html``) are separate steps; ``save_ai_scores`` folds fresh LLM scores
back into the shared ``scores_cache`` so the next run reuses them.
"""

import hashlib
import json
import logging
import re
from pathlib import Path

from linkedin_match import matching, scores_cache
from linkedin_match.connections import group_by_company, load_connections
from linkedin_match.jobs import attach_jobs, build_user_profile
from linkedin_match.models import Company, Job
from linkedin_match.textmatch import canonical_title, is_noise_title, title_relevant

logger = logging.getLogger("linkedin_match.report_prep")

SCORE_BATCHES = Path("data/score_batches.json")
REPORT_INPUT = Path("data/report_input.json")

BATCH_SIZE = 20        # jobs per Sonnet subagent call
DESC_TRIM = 600        # chars of description sent to the LLM per job
DEFAULT_MAX = 400      # cap on jobs sent to the LLM (and shown), by best keyword fit


def job_id(company: str, job: Job) -> str:
    """A stable short id for one job at one company (survives re-runs)."""
    raw = f"{company}|{job.title}|{job.url or ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def keep_job(job: Job, titles: list[str], exclude_titles: list[str] | None = None) -> bool:
    """Whether a job passes the report gate.

    Keep it only if its title matches a target title, contains none of the
    ``exclude_titles`` terms (free-text, whole-word — e.g. "senior", "manager",
    "qa"), is in Israel/remote, and isn't scraper-navigation noise.
    """
    return (
        title_relevant(job.title, titles)
        and not (exclude_titles and title_relevant(job.title, exclude_titles))
        and matching.is_relevant_location(job.location)
        and not is_noise_title(canonical_title(job.title or ""))
    )


def filter_companies(
    companies: list[Company], titles: list[str], exclude_titles: list[str] | None = None
) -> list[Company]:
    """Drop each company's off-target/excluded jobs, then drop companies left with none."""
    kept: list[Company] = []
    for company in companies:
        company.positions = [j for j in company.positions if keep_job(j, titles, exclude_titles)]
        if company.positions:
            kept.append(company)
    return kept


_REMOTE_RE = re.compile(r"remote|anywhere|wfh|work from home", re.IGNORECASE)

_city_match_cache: dict[str, str] | None = None


def clean_city(location: str | None) -> tuple[str, bool]:
    """Reduce a raw location (English or Hebrew) to ``(city, is_remote)``.

    Techmap's ``city`` column is plain Hebrew (e.g. "תל אביב-יפו"), and scraped
    career pages mix English and Hebrew text. Three tiers, cheapest first: the
    hardcoded known-city/alias table (``matching.canonical_city``, which already
    maps Hebrew names like "תל אביב" -> "Tel Aviv"); then ``data/city_matches.json``
    — a persistent cache of Sonnet's decisions for locations the alias table
    couldn't resolve (misspellings, unlisted cities, foreign locations), built by
    the optional flow in ``references/location-catalog.md`` and empty until that's
    been run at least once; only text matching neither falls back to stripping
    trailing punctuation and an "Israel" suffix.
    """
    global _city_match_cache
    text = (location or "").strip()
    if not text:
        return "", False
    if _REMOTE_RE.search(text):
        return "", True
    canonical = matching.canonical_city(text)
    if canonical:
        return canonical, False
    if _city_match_cache is None:
        from linkedin_match.location_catalog import load_city_match_cache
        _city_match_cache = load_city_match_cache()
    decision = _city_match_cache.get(text.casefold())
    if decision:
        if decision == "REMOTE":
            return "", True
        if decision == "NOT-ISRAEL":
            return "", False
        if decision.startswith("NEW:"):
            return decision[4:].strip(), False
        return decision, False
    text = text.replace("ישראל", "")
    text = re.split(r"[,\-·|/]", text)[0]
    text = re.sub(r"\bisrael\b", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" ,-"), False


def _job_location(job: Job) -> tuple[str, bool]:
    """Resolve a job's display ``(city, remote)`` by cleaning its raw location text."""
    return clean_city(job.location)


def _contact(conn) -> dict:
    """One contact pill: name, their role, and profile URL."""
    return {"name": conn.full_name, "role": conn.position or "", "url": conn.url}


def build_plan(
    companies: list[Company], titles: list[str], persona: str,
    candidate: str, blurb: str, cv_text: str = "", max_jobs: int = DEFAULT_MAX,
) -> tuple[dict, dict]:
    """Turn filtered companies into (report_input, score_batches) dicts.

    Pure and deterministic given the companies. Each kept job gets an id and a
    score-cache key (persona + titles + title + description); jobs already in
    ``scores_cache`` become ``cached_scores`` and skip the LLM. The rest are
    ranked by deterministic keyword fit, capped at ``max_jobs``, deduped by cache
    key (identical postings across companies score once), and batched.
    """
    profile = build_user_profile(cv_text, titles)  # target roles + CV skills, for cap ranking
    tkey = scores_cache.titles_key(titles)

    # Flatten to (company, job, id, cache_key, det_score); an id maps 1:1 to a job,
    # a cache_key may be shared by identical postings at different companies.
    flat: list[tuple[str, Job, str, str, int]] = []
    id_keys: dict[str, str] = {}
    for company in companies:
        for job in company.positions:
            jid = job_id(company.name, job)
            ckey = scores_cache.cache_key(tkey, job.title, job.description, persona)
            det = matching.score_job(job, profile)[0]
            flat.append((company.name, job, jid, ckey, det))
            id_keys[jid] = ckey

    try:
        cached = scores_cache.get_cached(sorted({ck for *_, ck, _ in flat}))
    except Exception as error:  # cache is best-effort; a miss just costs an LLM call
        logger.warning("score cache read failed: %s", error)
        cached = {}

    cached_scores = {jid: cached[ck] for _, _, jid, ck, _ in flat if ck in cached}

    # Uncached jobs: rank by keyword fit, cap, then keep one representative per
    # cache key so duplicate postings are scored once and fanned out on merge.
    uncached = sorted(
        [(name, job, jid, ck, det) for name, job, jid, ck, det in flat if ck not in cached],
        key=lambda r: r[4], reverse=True,
    )
    kept_ids: set[str] = set(cached_scores)
    reps: list[tuple[str, Job, str]] = []  # (rep_id, job, cache_key)
    seen_keys: set[str] = set()
    for name, job, jid, ck, _ in uncached:
        if ck not in seen_keys and len(reps) >= max_jobs:
            continue  # a brand-new key we have no budget for → drop this job entirely
        if ck not in seen_keys:
            seen_keys.add(ck)
            reps.append((jid, job, ck))
        kept_ids.add(jid)

    batches = [
        [
            {"id": jid, "title": job.title, "desc": (job.description or "")[:DESC_TRIM]}
            for jid, job, _ in reps[start:start + BATCH_SIZE]
        ]
        for start in range(0, len(reps), BATCH_SIZE)
    ]

    report_companies = []
    total_intros = 0
    for company in companies:
        jobs = []
        for j in company.positions:
            if job_id(company.name, j) not in kept_ids:
                continue
            city, remote = _job_location(j)
            jobs.append({"id": job_id(company.name, j), "title": j.title, "url": j.url,
                         "city": city, "remote": remote})
        if not jobs:
            continue
        contacts = [_contact(c) for c in company.connections]
        total_intros += len(contacts)
        report_companies.append({
            "company": company.name,
            "url": company.careers_url,
            "contacts": contacts,
            "jobs": jobs,
        })

    report_input = {
        "candidate": candidate,
        "titles": titles,
        "blurb": blurb,
        "persona": persona,
        "total_intros": total_intros,
        "companies": report_companies,
        "id_keys": {i: id_keys[i] for i in kept_ids},
        "cached_scores": cached_scores,
    }
    score_batches = {"persona": persona, "titles": titles, "batches": batches}
    return report_input, score_batches


def prepare(
    connections_path: Path, titles: list[str], persona: str, candidate: str,
    blurb: str, cv_text: str = "", exclude_titles: list[str] | None = None,
    max_jobs: int = DEFAULT_MAX,
    report_input_path: Path = REPORT_INPUT, batches_path: Path = SCORE_BATCHES,
) -> dict:
    """Full prep: load connections, attach scraped jobs, filter, and write both files.

    ``exclude_titles`` drops jobs whose title contains any of those (whole-word)
    terms. Returns a small summary ``{companies, jobs, to_score, batches, cached}``
    so the caller (the skill) can report progress and how many LLM batches to run.
    """
    companies = group_by_company(load_connections(connections_path))
    companies = attach_jobs(companies)  # fills company.positions from the jobs cache / techmap
    companies = filter_companies(companies, titles, exclude_titles)
    report_input, score_batches = build_plan(
        companies, titles, persona, candidate, blurb, cv_text=cv_text, max_jobs=max_jobs,
    )
    report_input_path.parent.mkdir(parents=True, exist_ok=True)
    report_input_path.write_text(json.dumps(report_input, ensure_ascii=False, indent=2), encoding="utf-8")
    batches_path.write_text(json.dumps(score_batches, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "companies": len(report_input["companies"]),
        "jobs": sum(len(c["jobs"]) for c in report_input["companies"]),
        "to_score": sum(len(b) for b in score_batches["batches"]),
        "batches": len(score_batches["batches"]),
        "cached": len(report_input["cached_scores"]),
    }


def save_ai_scores(
    ai_scores: dict, report_input: dict, model: str = "claude-sonnet",
) -> int:
    """Persist fresh LLM scores to the shared ``scores_cache``; return rows written.

    ``ai_scores`` is ``{rep_id: {"score", "tag"|"reason"}}`` from the subagents.
    Each rep_id maps through ``id_keys`` to a cache key; the score is stored once
    per key so the next run reuses it.
    """
    id_keys = report_input.get("id_keys", {})
    tkey = scores_cache.titles_key(report_input.get("titles", []))
    entries, seen = [], set()
    for rep_id, hit in ai_scores.items():
        ck = id_keys.get(rep_id)
        if not ck or ck in seen or hit is None:
            continue
        seen.add(ck)
        entries.append({
            "cache_key": ck, "company": None, "titles_key": tkey,
            "score": int(hit["score"]), "reason": hit.get("reason") or hit.get("tag"),
            "model": model,
        })
    if entries:
        try:
            scores_cache.save(entries)
        except Exception as error:
            logger.warning("score cache write failed: %s", error)
            return 0
    return len(entries)
