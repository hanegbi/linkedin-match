"""Parse and group a LinkedIn connections CSV export into companies."""

import csv
import json
import re
from pathlib import Path
from typing import Optional

from linkedin_match.models import Company, Connection

CONNECTIONS_JSON = Path("data/connections.json")

_HEADER_TOKENS = {"first name", "last name", "company"}


def find_connections_csv(root: Path = Path(".")) -> Optional[Path]:
    """Auto-discover a LinkedIn connections export CSV in the project root."""
    candidates = sorted(root.glob("*.csv"))
    preferred = [p for p in candidates if "connection" in p.name.lower()]
    for path in preferred + candidates:
        if _header_index(path) is not None:
            return path
    return None


def _header_index(path: Path) -> Optional[int]:
    """Return the line index of the real header row, skipping the notes preamble."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for index, line in enumerate(handle):
                cells = {c.strip().lower() for c in line.split(",")}
                if _HEADER_TOKENS.issubset(cells):
                    return index
    except OSError:
        return None
    return None


def _normalize_company(raw: str) -> str:
    """Strip and collapse whitespace in a raw company name."""
    return re.sub(r"\s+", " ", (raw or "").strip())


def load_connections(path: Path) -> list[Connection]:
    """Parse a LinkedIn export CSV into Connection models, skipping the preamble."""
    start = _header_index(path)
    if start is None:
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        lines = handle.readlines()
    reader = csv.DictReader(lines[start:])
    connections: list[Connection] = []
    for row in reader:
        company = _normalize_company(row.get("Company", ""))
        if not company:
            continue
        connections.append(
            Connection(
                first_name=(row.get("First Name") or "").strip(),
                last_name=(row.get("Last Name") or "").strip(),
                url=(row.get("URL") or "").strip() or None,
                email=(row.get("Email Address") or "").strip() or None,
                company=company,
                position=(row.get("Position") or "").strip() or None,
                connected_on=(row.get("Connected On") or "").strip() or None,
            )
        )
    return connections


def group_by_company(connections: list[Connection]) -> list[Company]:
    """Group connections into unique companies, deduped case-insensitively.

    Each company appears once; duplicate connections (same person and profile
    URL) at a company are collapsed so a contact is never listed twice.
    """
    buckets: dict[str, Company] = {}
    seen: dict[str, set[tuple[str, str]]] = {}
    for connection in connections:
        key = connection.company.casefold()
        company = buckets.get(key)
        if company is None:
            company = Company(name=connection.company)
            buckets[key] = company
            seen[key] = set()
        identity = (connection.full_name.casefold(), (connection.url or "").casefold())
        if identity in seen[key]:
            continue
        seen[key].add(identity)
        company.connections.append(connection)
    return sorted(buckets.values(), key=lambda c: c.name.casefold())


def build_connections_index(connections: list[Connection]) -> dict[str, list[dict]]:
    """Build a deduped company -> list of {name, url} index of my contacts."""
    index: dict[str, list[dict]] = {}
    for company in group_by_company(connections):
        index[company.name] = [
            {"name": c.full_name, "url": c.url} for c in company.connections
        ]
    return index


def write_connections_json(connections: list[Connection], path: Path = CONNECTIONS_JSON) -> tuple[Path, int]:
    """Write the deduped company -> contacts index to JSON and return (path, count)."""
    index = build_connections_index(connections)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    return path, len(index)
