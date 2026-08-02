"""Deterministic scoring and ranking of jobs against a CV-derived profile."""

import re

from linkedin_match.keywords import (
    CITY_ALIASES,
    ISRAEL_LOCATION_TERMS,
    OVERQUALIFIED_TITLE_TERMS,
    PINNED_COMPANIES,
    REMOTE_TERMS,
    ROLE_WEIGHTS,
    TITLE_EXCLUDE_KEYWORDS,
    TITLE_INCLUDE_KEYWORDS,
    USER_YEARS_EXPERIENCE,
)
from linkedin_match.models import Company, Job, Match, Profile

_PINNED = {name.casefold() for name in PINNED_COMPANIES}

ROLE_WEIGHT = 50
MUST_WEIGHT = 10
NICE_WEIGHT = 3
EXCLUDE_WEIGHT = -20
OVERQUALIFIED_PENALTY = -20
CITY_BOOST = 25
MUST_CAP = 50
NICE_CAP = 15
TITLE_SKILL_BONUS = 5
TITLE_SKILL_CAP = 20

FILTER_TITLES = True

_YEARS_PATTERN = re.compile(
    r"(\d{1,2})\s*\+\s*years|(?:at least|minimum(?: of)?|over)\s*(\d{1,2})\s*years|(\d{1,2})\s*-\s*\d{1,2}\s*years",
    re.IGNORECASE,
)


def title_is_relevant(title: str | None) -> bool:
    """Whether a job title matches CV-relevant roles and not an excluded one.

    Whole-word matching: the title must contain an include keyword (engineer /
    developer / software / infra / AI-ML, etc.) and no exclude keyword.
    """
    if not title:
        return False
    if any(_word_match(term, title) for term in TITLE_EXCLUDE_KEYWORDS):
        return False
    return any(_word_match(term, title) for term in TITLE_INCLUDE_KEYWORDS)


def is_relevant_location(location: str | None) -> bool:
    """Return whether a job location is Israel-based or remote.

    Empty locations are kept; only an explicit non-Israeli, non-remote location
    is dropped. Matching is whole-word, so foreign cities that merely contain an
    Israeli token as a substring (e.g. "Lodz" vs "Lod") are not counted.
    """
    if not location:
        return True
    if any(_word_match(term, location) for term in REMOTE_TERMS):
        return True
    return any(_word_match(term, location) for term in ISRAEL_LOCATION_TERMS)


def is_remote_location(location: str | None) -> bool:
    """Return whether a job location is explicitly remote (whole-word match)."""
    if not location:
        return False
    return any(_word_match(term, location) for term in REMOTE_TERMS)


def canonical_city(location: str | None) -> str | None:
    """Resolve a raw location to its canonical, title-cased city, or None.

    Aliases are matched whole-word to avoid substring false positives.
    """
    if not location:
        return None
    for city, aliases in CITY_ALIASES.items():
        if any(_word_match(alias, location) for alias in aliases):
            return city.title()
    return None


def city_terms(city: str | None) -> list[str]:
    """Resolve a user city selection to its location aliases (English + Hebrew).

    Matches the input against the canonical names and aliases in CITY_ALIASES;
    an unknown city falls back to matching its literal text.
    """
    if not city or not city.strip():
        return []
    key = city.strip().casefold()
    for canonical, aliases in CITY_ALIASES.items():
        if key == canonical or any(key == alias.casefold() for alias in aliases):
            return aliases
    return [city.strip()]


def _city_adjustment(location: str | None, terms: list[str]) -> tuple[int, str | None]:
    """Reward jobs whose location matches the user's selected city (whole-word)."""
    if not terms or not location:
        return 0, None
    if any(_word_match(term, location) for term in terms):
        return CITY_BOOST, f"city(+{CITY_BOOST})"
    return 0, None


def _word_match(term: str, text: str) -> bool:
    """Return whether a term appears in text as a whole, case-insensitive phrase."""
    pattern = r"\b" + re.escape(term) + r"\b"
    return re.search(pattern, text, re.IGNORECASE) is not None


def required_years(text: str) -> int | None:
    """Extract the highest required years-of-experience stated in the text."""
    found: list[int] = []
    for match in _YEARS_PATTERN.finditer(text):
        value = next((g for g in match.groups() if g), None)
        if value and 1 <= int(value) <= 25:
            found.append(int(value))
    return max(found) if found else None


def _experience_adjustment(text: str) -> tuple[int, str | None]:
    """Penalize roles demanding more years than the user has; reward a fit."""
    years = required_years(text)
    if years is None:
        return 0, None
    gap = years - USER_YEARS_EXPERIENCE
    if gap <= 0:
        return 5, f"exp:{years}y(fit)"
    if gap == 1:
        return 0, f"exp:{years}y"
    penalty = -(15 + (years - 6) * 5)
    return penalty, f"exp:{years}y({penalty})"


def _seniority_adjustment(title: str) -> tuple[int, str | None]:
    """Penalize titles implying seniority well above the user's experience."""
    if any(_word_match(term, title) for term in OVERQUALIFIED_TITLE_TERMS):
        return OVERQUALIFIED_PENALTY, f"senior({OVERQUALIFIED_PENALTY})"
    return 0, None


def score_job(
    job: Job, profile: Profile, preferred_city: list[str] | None = None
) -> tuple[int, list[str]]:
    """Score a job against the profile with deterministic whole-word matching.

    Args:
        job: The position to score.
        profile: The keyword profile derived from the CV.
        preferred_city: Location aliases of a selected city to boost (optional).

    Returns:
        A tuple of the integer score and the list of contributing keywords.
    """
    title = job.title or ""
    haystack = f"{job.title}\n{job.description}\n{job.department or ''}"
    score = 0
    matched: list[str] = []
    best_role = 0
    role_words: set[str] = set()
    for role in profile.target_roles:
        if _word_match(role, title):
            weight = ROLE_WEIGHTS.get(role, ROLE_WEIGHT)
            if weight > best_role:
                best_role = weight
            matched.append(role)
            role_words.update(role.split())
    score += best_role

    def _is_role_word(term: str) -> bool:
        """Whether a skill term is wholly contained in a matched role's words."""
        return all(word in role_words for word in term.split())

    must_pts = 0
    title_skill = 0
    for term in profile.must_have_keywords:
        if _is_role_word(term):
            continue
        if _word_match(term, haystack):
            must_pts += MUST_WEIGHT
            matched.append(term)
            if _word_match(term, title):
                title_skill += TITLE_SKILL_BONUS
    nice_pts = 0
    for term in profile.nice_to_have_keywords:
        if _is_role_word(term):
            continue
        if _word_match(term, haystack):
            nice_pts += NICE_WEIGHT
            matched.append(term)
            if _word_match(term, title):
                title_skill += TITLE_SKILL_BONUS
    score += min(must_pts, MUST_CAP) + min(nice_pts, NICE_CAP) + min(title_skill, TITLE_SKILL_CAP)
    for term in profile.exclude_keywords:
        if _word_match(term, haystack):
            score += EXCLUDE_WEIGHT
            matched.append(f"-{term}")
    seniority_text = f"{title} {job.employment_type or ''}"
    for delta, note in (_experience_adjustment(haystack), _seniority_adjustment(seniority_text)):
        if note:
            score += delta
            matched.append(note)
    if score > 0:
        delta, note = _city_adjustment(job.location, preferred_city or [])
        if note:
            score += delta
            matched.append(note)
    return score, matched


def match_company(
    company: Company, profile: Profile, preferred_city: list[str] | None = None
) -> list[Match]:
    """Score every position at a company, carrying through my connections there."""
    matches: list[Match] = []
    for job in company.positions:
        score, matched = score_job(job, profile, preferred_city)
        matches.append(
            Match(
                company=company.name,
                connections=company.connections,
                job=job,
                score=score,
                matched_keywords=matched,
            )
        )
    return matches


def rank_matches(
    companies: list[Company], profile: Profile, city: str | None = None
) -> list[Match]:
    """Score positions, keep Israel/remote, normalize to 1-100, sort best-first.

    Raw points are preserved in `raw_score`; `score` is rescaled so the strongest
    match is 100 and the rest are proportional (floored at 1). When `city` is set,
    jobs in that city are boosted but jobs elsewhere are still kept.
    """
    preferred_city = city_terms(city)
    matches: list[Match] = []
    for company in companies:
        matches.extend(match_company(company, profile, preferred_city))
    relevant = [
        m
        for m in matches
        if (m.score > 0 or m.company.casefold() in _PINNED)
        and is_relevant_location(m.job.location)
        and (not FILTER_TITLES or title_is_relevant(m.job.title))
    ]
    relevant.sort(key=lambda m: m.score, reverse=True)
    if not relevant:
        return relevant
    top = max(relevant[0].score, 1)
    for match in relevant:
        match.raw_score = match.score
        match.score = max(1, round(match.score / top * 100))
    return relevant
