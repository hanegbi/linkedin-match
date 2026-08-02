"""Scraper settings loaded from the environment or a local .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed scraper settings sourced from the environment or a ``.env`` file."""

    scrape_ttl_hours: int = 24
    scrape_workers: int = 6
    scores_ttl_days: int = 30

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
