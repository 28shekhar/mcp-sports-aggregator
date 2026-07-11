"""
MCP server: Indian News Sports Aggregator.

Exposes cached, sports-prioritized news stories (aggregated from three
Indian news sites) as MCP tools that Claude can call. Runs over
Streamable HTTP so it can be deployed as a long-lived service on
Hugging Face Spaces and registered with Claude as a remote MCP server.

Tools exposed:
  - get_top_stories(limit=30, sports_only=False): the cached, ranked stories
  - cache_status(): freshness/count diagnostics
  - refresh_now(): force an immediate re-fetch (bypasses the hourly schedule)

Run locally:
    python server.py

Environment variables: see .env.example / README.md.
"""
from __future__ import annotations

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp.server.fastmcp import FastMCP

from cache import story_cache
from config import settings
from scheduler import refresh_cache, start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("server")

mcp = FastMCP(
    "indian-news-sports-aggregator",
    host=settings.host,
    port=settings.port,
    stateless_http=True,
)


@mcp.tool()
def get_top_stories(limit: int = 30, sports_only: bool = False) -> list[dict]:
    """Return cached top news stories, sports content ranked first.

    Args:
        limit: max number of stories to return (default 30, i.e. the
            guaranteed minimum cache size).
        sports_only: if True, return only stories classified as sports.

    Returns:
        A list of story dicts, each with: title, url, source, category
        ("sports" or "general"), is_sports, published_at, fetched_at.
    """
    return story_cache.get_stories(limit=limit, sports_only=sports_only)


@mcp.tool()
def cache_status() -> dict:
    """Return cache diagnostics: total/sports/general counts and last refresh time."""
    return story_cache.status()


@mcp.tool()
def refresh_now() -> dict:
    """Force an immediate fetch+classify+cache-update cycle for all three sites,
    bypassing the hourly schedule. Returns the resulting cache status."""
    return refresh_cache()


@mcp.tool()
def list_sources() -> list[dict]:
    """List the three configured source websites currently being aggregated."""
    return [{"name": s.name, "url": s.url} for s in settings.sites]


def _add_health_route():
    """Add a plain HTTP /health route alongside the MCP endpoint, so
    Hugging Face Spaces (and any uptime monitor) can check liveness without
    speaking MCP."""
    async def health(request: Request):
        status = story_cache.status()
        return JSONResponse({"ok": True, "cache": status})

    try:
        app = mcp.streamable_http_app()
    except AttributeError:
        app = mcp.sse_app()
    app.router.routes.append(Route("/health", health))


def main():
    logger.info("Starting Indian News Sports Aggregator MCP server")
    logger.info("Configured sources: %s", [s.name for s in settings.sites])
    logger.info("Groq classification enabled: %s", bool(settings.groq_api_key))

    # Populate the cache synchronously before accepting traffic so the very
    # first tool call already has >= min_cached_stories stories, instead of
    # waiting for the first hourly tick.
    logger.info("Running initial cache fetch...")
    refresh_cache()

    # Kick off the hourly (configurable) background refresh job.
    start_scheduler()

    _add_health_route()

    mcp.run(transport=settings.mcp_transport)


if __name__ == "__main__":
    main()
