"""Whole-word text matching and title normalization shared across the app.

A single implementation of "does this term appear as a whole word", the
title-relevance gate it powers, and the canonical-title reducer used to
aggregate messy market titles — so the web service and the title board apply
identical rules instead of each carrying their own regex.
"""

import re


def word_in(term: str, text: str) -> bool:
    """Whether ``term`` appears in ``text`` as a whole word (case-insensitive).

    Boundaries treat ``+ # .`` as word characters so tokens like ``c++`` and
    ``.net`` match exactly and don't bleed into neighbouring words.
    """
    return re.search(r"(?<![\w+#.])" + re.escape(term) + r"(?![\w+#])", text, re.IGNORECASE) is not None


def title_relevant(title: str | None, titles: list[str]) -> bool:
    """Keep a job whose title contains one of the user's target titles.

    The user's chosen titles are the only filter, so the app works for any role
    (engineering, customer success, TAM, product, …), not just a preset list.
    """
    if not title:
        return False
    return any(word_in(x, title) for x in titles)


_SENIORITY = re.compile(
    r"\b(senior|sr\.?|junior|jr\.?|lead|principal|staff|entry[- ]level|intern|experienced|associate|head of)\b",
    re.IGNORECASE,
)
_LEVEL = re.compile(r"\s+(?:[ivx]+|\d+)$", re.IGNORECASE)  # trailing level: "II", "3"
# Career-page button/navigation text that scrapers store as job titles. Matched
# as substrings of the canonical role so a role containing any is dropped.
_NOISE_MARKERS = (
    "apply now", "apply today", "read more", "learn more", "show more", "see more",
    "see open", "open position", "view job", "view role", "view all", "search job",
    "browse job", "master class", "join our", "get started", "sign in", "log in",
    "talent community", "all positions", "explore role",
)


def canonical_title(title: str) -> str:
    """Reduce a job title to its core role, so variants aggregate together.

    Splits off qualifiers, drops seniority words, then strips stray leading/
    trailing punctuation (bullets like ".", "+") and a trailing level ("II", "3")
    so "Senior Backend Engineer, Payments" and "Backend Engineer II" both collapse
    to "backend engineer".
    """
    head = re.split(r"[,\-–—|/(]", title, maxsplit=1)[0]
    head = _SENIORITY.sub(" ", head)
    head = re.sub(r"\s+", " ", head).strip().lower()
    head = re.sub(r"^[^a-z]+|[^a-z]+$", "", head)
    return _LEVEL.sub("", head).strip()


def is_noise_title(role: str) -> bool:
    """Whether a canonical role is scraper navigation text, not a real job title."""
    return any(marker in role for marker in _NOISE_MARKERS)
