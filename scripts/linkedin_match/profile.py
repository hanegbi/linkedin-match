"""Build a matching Profile from a CV file: text extraction plus seniority."""

import logging
import re
from pathlib import Path
from typing import Optional

import linkedin_match.keywords as kw
from linkedin_match.models import Profile

logger = logging.getLogger("linkedin_match.profile")


def find_cv(root: Path = Path(".")) -> Optional[Path]:
    """Auto-discover a CV (.docx/.pdf) or a brief (.txt/.md) in the project root."""
    brief = sorted(root.glob("brief.txt")) + sorted(root.glob("brief.md"))
    candidates = sorted(root.glob("*.docx")) + sorted(root.glob("*.pdf"))
    candidates = [p for p in candidates if not p.name.startswith("~$")]
    return (brief + candidates)[0] if (brief or candidates) else None


def extract_cv_text(path: Path) -> str:
    """Extract plain text from a CV file, dispatching by file extension."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8")
    raise ValueError(f"Unsupported CV type: {suffix}")


def _extract_docx(path: Path) -> str:
    """Extract text from a .docx file via python-docx."""
    from docx import Document

    document = Document(str(path))
    return "\n".join(p.text for p in document.paragraphs)


def _extract_pdf(path: Path) -> str:
    """Extract text from a .pdf via pypdf, falling back to pdfplumber if empty."""
    from pypdf import PdfReader

    text = ""
    try:
        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as error:
        logger.debug("pypdf failed for %s: %s", path, error)
    if text.strip():
        return text
    import pdfplumber

    with pdfplumber.open(str(path)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def _word_match(term: str, text: str) -> bool:
    """Return whether a term appears in text as a whole, case-insensitive phrase."""
    pattern = r"\b" + re.escape(term) + r"\b"
    return re.search(pattern, text, re.IGNORECASE) is not None


def _detect_seniority(text: str) -> Optional[str]:
    """Infer a single seniority level from the CV text, highest match wins."""
    for level in ("principal", "senior", "mid", "junior"):
        if any(_word_match(term, text) for term in kw.SENIORITY_TERMS[level]):
            return level
    return None


def build_profile(cv_text: str) -> Profile:
    """Build a Profile from the curated keyword config and CV text.

    The curated role/skill lists are used as-is; only seniority is inferred from
    the CV.

    Args:
        cv_text: The extracted plain text of the CV.

    Returns:
        The curated roles and keyword buckets plus the detected seniority.
    """
    roles = list(kw.TARGET_ROLES)
    must = list(kw.MUST_HAVE_KEYWORDS)
    nice = list(kw.NICE_TO_HAVE_KEYWORDS)
    return Profile(
        target_roles=roles,
        must_have_keywords=must,
        nice_to_have_keywords=nice,
        exclude_keywords=list(kw.EXCLUDE_KEYWORDS),
        seniority=_detect_seniority(cv_text),
    )
