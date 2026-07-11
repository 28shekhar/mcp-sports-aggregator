"""
Central configuration for the Indian News Sports Aggregator MCP server.

Every credential and site URL is read from environment variables — nothing
is hardcoded. Copy `.env.example` to `.env` (locally) or set these as
Hugging Face Space "Repository secrets" / "Variables" when deploying.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class SiteConfig:
    name: str
    url: str


@dataclass(frozen=True)
class Settings:
    # --- Source websites (three, user-configurable) ---
    site_1_name: str = os.environ.get("NEWS_SITE_1_NAME", "Times of India")
    site_1_url: str = os.environ.get(
        "NEWS_SITE_1_URL", "https://timesofindia.indiatimes.com"
    )
    site_2_name: str = os.environ.get("NEWS_SITE_2_NAME", "Hindustan Times")
    site_2_url: str = os.environ.get(
        "NEWS_SITE_2_URL", "https://www.hindustantimes.com"
    )
    site_3_name: str = os.environ.get("NEWS_SITE_3_NAME", "NDTV")
    site_3_url: str = os.environ.get("NEWS_SITE_3_URL", "https://www.ndtv.com")

    # --- Groq API (used for LLM-assisted sports classification) ---
    groq_api_key: str = os.environ.get("GROQ_API_KEY", "")
    groq_model: str = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
    groq_enabled: bool = _env_bool("GROQ_ENABLED", True)

    # --- Cache / scheduler behaviour ---
    min_cached_stories: int = int(os.environ.get("MIN_CACHED_STORIES", "30"))
    max_cached_stories: int = int(os.environ.get("MAX_CACHED_STORIES", "150"))
    refresh_interval_minutes: int = int(
        os.environ.get("REFRESH_INTERVAL_MINUTES", "60")
    )
    stories_per_site_fetch: int = int(os.environ.get("STORIES_PER_SITE_FETCH", "25"))
    request_timeout_seconds: int = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "12"))
    user_agent: str = os.environ.get(
        "SCRAPER_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    )

    # --- Server ---
    host: str = os.environ.get("HOST", "0.0.0.0")
    port: int = int(os.environ.get("PORT", "7860"))
    mcp_transport: str = os.environ.get("MCP_TRANSPORT", "streamable-http")

    # --- Persistence ---
    cache_snapshot_path: str = os.environ.get(
        "CACHE_SNAPSHOT_PATH", "cache_snapshot.json"
    )

    @property
    def sites(self) -> list:
        return [
            SiteConfig(self.site_1_name, self.site_1_url),
            SiteConfig(self.site_2_name, self.site_2_url),
            SiteConfig(self.site_3_name, self.site_3_url),
        ]


settings = Settings()
