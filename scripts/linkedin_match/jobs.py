"""Attach open jobs to companies and build a matching profile from a CV.

The two pieces the report/scoring flow needs: ``attach_jobs`` fills each
company's open positions from the JSON jobs cache built by ``app.py hybrid``
(falling back to the techmap dataset live if the cache is empty), and
``build_user_profile`` turns the CV text + chosen titles into a ``Profile`` for
deterministic ranking. Plain JSON, no database — this is a small personal tool
meant to run on one job searcher's own computer.
"""

from linkedin_match import techmap
from linkedin_match.cache import load_cache
from linkedin_match.fetchers import make_session
from linkedin_match.models import Company, Profile
from linkedin_match.scraper import companies_from_cache
from linkedin_match.textmatch import word_in

# Known tech/role skills we pull out of a CV to seed the deterministic profile.
SKILLS_VOCAB: list[str] = [
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "golang", "rust",
    "ruby", "php", "scala", "kotlin", "swift", "objective-c",
    "react", "angular", "vue", "svelte", "next.js", "node", "node.js", "django",
    "flask", "fastapi", "spring", ".net", "express", "rails", "laravel",
    "sql", "postgresql", "postgres", "mysql", "mongodb", "redis", "cassandra",
    "kafka", "rabbitmq", "elasticsearch", "graphql", "grpc", "rest", "microservices",
    "docker", "kubernetes", "terraform", "ansible", "helm", "aws", "gcp", "azure",
    "ci/cd", "jenkins", "github actions", "git", "linux", "bash",
    "machine learning", "deep learning", "pytorch", "tensorflow", "scikit-learn",
    "nlp", "llm", "rag", "computer vision", "data science", "pandas", "numpy",
    "spark", "hadoop", "airflow", "etl", "snowflake", "databricks",
    "devops", "sre", "observability", "prometheus", "grafana", "datadog",
    "html", "css", "sass", "tailwind", "webpack", "android", "ios", "flutter",
    "selenium", "cypress", "playwright", "pytest",
    "salesforce", "hubspot", "gainsight", "zendesk", "intercom", "crm", "saas",
    "onboarding", "account management", "customer success", "churn", "renewals",
    "upsell", "jira", "confluence", "agile", "scrum", "kanban", "tableau", "looker",
    "power bi", "product management", "roadmap", "stakeholder management", "b2b",
]


def extract_skills(text: str) -> list[str]:
    """Pull known tech skills out of the CV / brief text."""
    return [s for s in SKILLS_VOCAB if word_in(s, text or "")]


def build_user_profile(cv_text: str, titles: list[str]) -> Profile:
    """Build a Profile from the user's free text and chosen titles."""
    return Profile(
        target_roles=titles,
        must_have_keywords=extract_skills(cv_text),
        nice_to_have_keywords=[],
        exclude_keywords=[],
    )


def attach_jobs(companies: list[Company]) -> list[Company]:
    """Attach open positions to each company from the JSON jobs cache, or techmap.

    Reads ``data/jobs_cache.json`` (built by ``app.py hybrid``) when it has
    entries for these companies; otherwise falls back to indexing the techmap
    dataset live. Returns the companies with ``positions``/``status`` filled in.
    """
    cache = load_cache()
    if cache:
        return companies_from_cache(companies, cache)
    techmap.companies_with_jobs(companies, make_session())
    return companies
