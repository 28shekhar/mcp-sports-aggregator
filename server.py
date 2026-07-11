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

import html
import logging
from datetime import datetime

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

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


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Plain HTTP health check alongside the MCP endpoint, so Hugging Face
    Spaces (and any uptime monitor) can check liveness without speaking MCP."""
    status = story_cache.status()
    return JSONResponse({"ok": True, "cache": status})


@mcp.custom_route("/stories", methods=["GET"])
async def stories(request: Request) -> JSONResponse:
    """Plain HTTP JSON view of the cached stories, for browsing outside MCP."""
    sports_only = request.query_params.get("sports_only", "").lower() in ("1", "true", "yes")
    limit = int(request.query_params.get("limit", settings.min_cached_stories))
    return JSONResponse(story_cache.get_stories(limit=limit, sports_only=sports_only))


def _format_fetched_at(iso_timestamp: str | None) -> str:
    if not iso_timestamp:
        return "unknown time"
    try:
        return datetime.fromisoformat(iso_timestamp).strftime("%b %d, %Y · %H:%M UTC")
    except ValueError:
        return iso_timestamp


@mcp.custom_route("/", methods=["GET"])
async def index(request: Request) -> HTMLResponse:
    """Minimal HTML page listing cached headlines as clickable links, so the
    scraped news data can be browsed in a regular browser without an MCP
    client. Not a production UI, just a local-viewing convenience."""
    items = story_cache.get_stories(limit=settings.max_cached_stories)
    rows = "\n".join(
        f'<li><span class="tag {"sports" if s.get("is_sports") else "general"}">'
        f'{html.escape(s.get("category", ""))}</span> '
        f'<a href="{html.escape(s["url"])}" target="_blank" rel="noopener noreferrer">'
        f'{html.escape(s["title"])}</a> '
        f'<span class="source">— {html.escape(s.get("source", ""))}</span>'
        f'<br><span class="fetched_at">Fetched {html.escape(_format_fetched_at(s.get("fetched_at")))}</span></li>'
        for s in items
    )
    page = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Indian News Sports Aggregator</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.3rem; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ padding: 0.5rem 0; border-bottom: 1px solid #ddd; }}
  a {{ text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .tag {{ font-size: 0.7rem; text-transform: uppercase; padding: 0.1rem 0.4rem; border-radius: 3px; margin-right: 0.4rem; }}
  .tag.sports {{ background: #d6f5d6; color: #1a6b1a; }}
  .tag.general {{ background: #e6e6e6; color: #555; }}
  .source {{ color: #888; font-size: 0.85rem; }}
  .fetched_at {{ color: #aaa; font-size: 0.78rem; }}
</style>
</head>
<body>
<h1>Indian News Sports Aggregator — {len(items)} cached stories</h1>
<ul>
{rows}
</ul>
</body>
</html>"""
    return HTMLResponse(page)


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

    mcp.run(transport=settings.mcp_transport)


if __name__ == "__main__":
    main()
