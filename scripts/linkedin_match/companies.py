"""Company-name heuristics and shared constants for discovery and scraping."""

COMPANY_OVERRIDES: dict[str, dict] = {}

GENERIC_NAME_WORDS: set[str] = {
    "the",
    "inc",
    "ltd",
    "llc",
    "co",
    "corp",
    "group",
    "solutions",
    "technologies",
    "technology",
    "labs",
    "systems",
    "software",
    "global",
    "international",
    "ai",
    "io",
    "app",
    "platform",
    "company",
}

ATS_ORDER: list[str] = ["greenhouse", "lever", "ashby", "workable", "comeet"]

NOISE_COMPANY_TERMS: list[str] = [
    "freelance",
    "stealth",
    "self-employed",
    "self employed",
    "unemployed",
    "confidential",
    "undisclosed",
    "various",
    "open to work",
    "looking for",
    "recruit",
    "recruiting",
    "recruitment",
    "talent acquisition",
    "manpower",
    "staffing",
    "gotfriends",
    "techjob",
    "jobinfo",
    "job info",
    "cyber security company",
]


def is_noise_company(name: str) -> bool:
    """Whether a company name is a placeholder or recruiter rather than an employer."""
    lowered = (name or "").casefold()
    return any(term in lowered for term in NOISE_COMPANY_TERMS)

DOMAIN_TLDS: list[str] = [".com", ".ai", ".io", ".co", ".co.il", ".net", ".tech"]

CAREERS_URL_PATTERNS: list[str] = [
    "/careers",
    "/careers/",
    "/jobs",
    "/jobs/",
    "/career",
    "/about-us/careers/",
    "/about/careers/",
    "/company/careers/",
    "/join-us/",
    "/join/",
]

CAREERS_LINK_TERMS: list[str] = [
    "career",
    "careers",
    "jobs",
    "join us",
    "join our team",
    "join the team",
    "work with us",
    "open position",
    "open roles",
    "we are hiring",
    "we're hiring",
    "vacanc",
    "life at",
]
