"""Pydantic models shared across the app: connections, jobs, companies, matches."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Connection(BaseModel):
    """A single LinkedIn connection from the exported CSV."""

    first_name: str
    last_name: str
    url: Optional[str] = None
    email: Optional[str] = None
    company: str
    position: Optional[str] = None
    connected_on: Optional[str] = None

    @property
    def full_name(self) -> str:
        """Return the connection's full display name."""
        return f"{self.first_name} {self.last_name}".strip()


class Job(BaseModel):
    """A normalized open position scraped from a company source."""

    title: str
    location: Optional[str] = None
    url: Optional[str] = None
    description: str = ""
    department: Optional[str] = None
    employment_type: Optional[str] = None
    posted_at: Optional[str] = None


class Company(BaseModel):
    """A unique company plus my warm-intro connections there and its jobs."""

    name: str
    connections: list[Connection] = Field(default_factory=list)
    careers_url: Optional[str] = None
    source: Optional[str] = None
    status: str = "pending"
    scraped_at: Optional[str] = None
    positions: list[Job] = Field(default_factory=list)


class Profile(BaseModel):
    """My derived profile built deterministically from the CV text."""

    target_roles: list[str] = Field(default_factory=list)
    must_have_keywords: list[str] = Field(default_factory=list)
    nice_to_have_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    seniority: Optional[str] = None


class Match(BaseModel):
    """A scored pairing of a position with the company and my contacts there."""

    company: str
    connections: list[Connection] = Field(default_factory=list)
    job: Job
    score: int
    raw_score: Optional[int] = None
    reason: Optional[str] = None
    matched_keywords: list[str] = Field(default_factory=list)
    company_size: Optional[str] = None
    company_locations: Optional[str] = None
