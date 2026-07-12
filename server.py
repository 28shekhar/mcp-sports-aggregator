"""
MCP server: Indian News Sports Aggregator.

Exposes cached, cricket/football/tennis-prioritized news stories (aggregated
from three Indian news sites and two US news sites) as MCP tools that
Claude can call. Runs over
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
from datetime import datetime, timedelta, timezone

from starlette.concurrency import run_in_threadpool
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
    """Return cached top news stories, cricket/football/tennis content ranked first.

    Args:
        limit: max number of stories to return (default 30, i.e. the
            guaranteed minimum cache size).
        sports_only: if True, return only cricket/football/tennis stories
            (excludes "general").

    Returns:
        A list of story dicts, each with: title, url, source, category
        ("cricket", "football", "tennis", or "general"), is_sports,
        published_at, fetched_at.
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


@mcp.custom_route("/refresh", methods=["POST"])
async def refresh(request: Request) -> JSONResponse:
    """Trigger an immediate fetch+classify+cache-update cycle, for the
    viewer's manual refresh button. Runs the (blocking) scrape in a
    thread so it doesn't stall the async event loop."""
    status = await run_in_threadpool(refresh_cache)
    return JSONResponse({"ok": True, "cache": status})


IST = timezone(timedelta(hours=5, minutes=30))


def _format_fetched_at(iso_timestamp: str | None) -> str:
    if not iso_timestamp:
        return "unknown time"
    try:
        return datetime.fromisoformat(iso_timestamp).astimezone(IST).strftime("%b %d, %Y · %H:%M IST")
    except ValueError:
        return iso_timestamp


def _fetched_within_last_24h(story: dict) -> bool:
    fetched_at = story.get("fetched_at")
    if not fetched_at:
        return False
    try:
        fetched_dt = datetime.fromisoformat(fetched_at)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - fetched_dt <= timedelta(hours=24)


# Deterministic gradient palette for card/hero thumbnails, since scraped
# headlines carry no real images. Cycled by index for visual variety.
_CARD_GRADIENTS = [
    "linear-gradient(135deg, #2b3a55, #4d6a8a)",
    "linear-gradient(135deg, #3a2b55, #6a4d8a)",
    "linear-gradient(135deg, #1f4d40, #3d8a6a)",
    "linear-gradient(135deg, #55402b, #8a6a4d)",
    "linear-gradient(135deg, #2b4a55, #4d7d8a)",
    "linear-gradient(135deg, #4a2b55, #7d4d8a)",
]
_HERO_GRADIENT = "linear-gradient(160deg, #1b2a4a 0%, #2f4d6b 45%, #3f6b55 100%)"


def _card_html(s: dict, index: int) -> str:
    category = s.get("category", "general")
    gradient = _CARD_GRADIENTS[index % len(_CARD_GRADIENTS)]
    return f"""
<a class="card" data-category="{category}" href="{html.escape(s["url"])}" target="_blank" rel="noopener noreferrer">
  <div class="card-thumb" style="background: {gradient}">
    <span class="tag {category}">{html.escape(s.get("category", ""))}</span>
  </div>
  <div class="card-body">
    <h3>{html.escape(s["title"])}</h3>
    <div class="meta">
      <span class="source">{html.escape(s.get("source", ""))}</span>
      <span class="dot">·</span>
      <span class="fetched_at">{html.escape(_format_fetched_at(s.get("fetched_at")))}</span>
    </div>
  </div>
</a>"""


def _sidebar_item_html(s: dict, rank: int) -> str:
    return f"""
<a class="sidebar-item" href="{html.escape(s["url"])}" target="_blank" rel="noopener noreferrer">
  <span class="rank">{rank}</span>
  <div>
    <h4>{html.escape(s["title"])}</h4>
    <div class="meta">
      <span class="source">{html.escape(s.get("source", ""))}</span>
      <span class="dot">·</span>
      <span class="fetched_at">{html.escape(_format_fetched_at(s.get("fetched_at")))}</span>
    </div>
  </div>
</a>"""


@mcp.custom_route("/", methods=["GET"])
async def index(request: Request) -> HTMLResponse:
    """Dark-themed HTML page listing cached headlines as a hero + card grid
    + top-stories sidebar, so the scraped news data can be browsed in a
    regular browser without an MCP client. Not a production UI, just a
    local-viewing convenience — thumbnails are gradient placeholders since
    scraped headlines carry no real images."""
    all_items = story_cache.get_stories(limit=settings.max_cached_stories)
    items = [s for s in all_items if _fetched_within_last_24h(s)]

    if not items:
        message = (
            "No stories cached yet"
            if not all_items
            else "No stories fetched in the past 24 hours"
        )
        return HTMLResponse(
            "<!doctype html><html><body style='background:#0b0b0f;color:#eee;"
            "font-family:system-ui,sans-serif;padding:2rem'>"
            f"<h1>{html.escape(message)}</h1>"
            "<p>Call refresh_now or wait for the next scheduled refresh.</p>"
            "</body></html>"
        )

    cricket_count = sum(1 for s in items if s.get("category") == "cricket")
    football_count = sum(1 for s in items if s.get("category") == "football")
    tennis_count = sum(1 for s in items if s.get("category") == "tennis")
    general_count = len(items) - cricket_count - football_count - tennis_count

    hero, rest = items[0], items[1:]
    top5 = items[:5]

    cards_html = "\n".join(_card_html(s, i) for i, s in enumerate(rest))
    sidebar_html = "\n".join(_sidebar_item_html(s, i + 1) for i, s in enumerate(top5))

    page = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Indian News Sports Aggregator</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, system-ui, sans-serif;
    background: #0b0b0f; color: #f2f2f5;
    margin: 0; padding: 2rem clamp(1rem, 4vw, 3rem) 4rem;
  }}
  a {{ color: inherit; text-decoration: none; }}
  h1, h2, h3, h4 {{ margin: 0; }}

  .hero {{
    position: relative; border-radius: 16px; overflow: hidden;
    padding: 4rem 2rem; text-align: center; margin-bottom: 2rem;
    background: {_HERO_GRADIENT};
  }}
  .hero .spotlight {{ color: #ffd76a; font-weight: 600; letter-spacing: 0.05em; }}
  .hero h1 {{ font-size: clamp(1.6rem, 4vw, 2.6rem); margin: 0.75rem 0 1rem; line-height: 1.25; }}
  .hero a.title-link:hover {{ text-decoration: underline; }}
  .hero .meta {{ color: #d8d8de; font-size: 0.9rem; }}

  .scope-note {{ color: #8a8a99; font-size: 0.85rem; margin-bottom: 0.75rem; }}
  .pills-row {{
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 0.75rem; margin-bottom: 2rem;
  }}
  .pills {{ display: flex; gap: 0.6rem; flex-wrap: wrap; }}
  .pill {{
    background: #1a1a22; border: 1px solid #2a2a35; border-radius: 999px;
    padding: 0.5rem 1rem; font-size: 0.85rem; color: #cfcfd6; cursor: pointer;
  }}
  .pill.active {{ background: #2a2a3d; color: #fff; border-color: #4d4d6a; }}
  .pill .count {{ color: #8a8a99; margin-left: 0.35rem; }}

  .refresh-btn {{
    background: #2a2a3d; border: 1px solid #4d4d6a; border-radius: 999px;
    padding: 0.5rem 1.1rem; font-size: 0.85rem; color: #fff; cursor: pointer;
    font-family: inherit;
  }}
  .refresh-btn:hover {{ background: #34344a; }}
  .refresh-btn:disabled {{ opacity: 0.6; cursor: default; }}

  .layout {{ display: grid; grid-template-columns: 1fr 320px; gap: 2rem; align-items: start; }}
  @media (max-width: 900px) {{ .layout {{ grid-template-columns: 1fr; }} }}

  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 1.25rem; }}
  .card {{
    display: block; background: #15151b; border: 1px solid #232330; border-radius: 12px;
    overflow: hidden; transition: transform 0.15s ease, border-color 0.15s ease;
  }}
  .card:hover {{ transform: translateY(-2px); border-color: #3a3a4d; }}
  .card.hidden {{ display: none; }}
  .card-thumb {{ height: 110px; position: relative; padding: 0.6rem; }}
  .card-body {{ padding: 0.9rem 1rem 1.1rem; }}
  .card-body h3 {{ font-size: 0.98rem; line-height: 1.35; font-weight: 600; }}

  .tag {{
    font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.03em;
    padding: 0.15rem 0.5rem; border-radius: 4px; font-weight: 700;
  }}
  .tag.cricket {{ background: #d6f5d6; color: #1a6b1a; }}
  .tag.football {{ background: #d6e8ff; color: #1a4d8f; }}
  .tag.tennis {{ background: #ffe8d6; color: #8f4d1a; }}
  .tag.general {{ background: #e6e6e6; color: #555; }}

  .meta {{ margin-top: 0.5rem; font-size: 0.78rem; color: #9a9aa5; }}
  .meta .dot {{ margin: 0 0.35rem; }}

  .sidebar h2 {{ font-size: 1.1rem; margin-bottom: 1rem; }}
  .sidebar-item {{ display: flex; gap: 0.75rem; padding: 0.85rem 0; border-bottom: 1px solid #202028; }}
  .sidebar-item:hover h4 {{ text-decoration: underline; }}
  .sidebar-item .rank {{
    font-size: 1.3rem; font-weight: 800; color: #4d4d6a; min-width: 1.3rem;
  }}
  .sidebar-item h4 {{ font-size: 0.9rem; line-height: 1.3; font-weight: 600; }}
</style>
</head>
<body>

<div class="hero">
  <div class="spotlight">✦ IN THE SPOTLIGHT</div>
  <h1><a class="title-link" href="{html.escape(hero["url"])}" target="_blank" rel="noopener noreferrer">{html.escape(hero["title"])}</a></h1>
  <div class="meta">{html.escape(hero.get("source", ""))} · {html.escape(_format_fetched_at(hero.get("fetched_at")))}</div>
</div>

<div class="scope-note">Showing stories fetched in the past 24 hours</div>
<div class="pills-row">
  <div class="pills">
    <div class="pill active" data-filter="all">All <span class="count">{len(items)}</span></div>
    <div class="pill" data-filter="cricket">Cricket <span class="count">{cricket_count}</span></div>
    <div class="pill" data-filter="football">Football <span class="count">{football_count}</span></div>
    <div class="pill" data-filter="tennis">Tennis <span class="count">{tennis_count}</span></div>
    <div class="pill" data-filter="general">General <span class="count">{general_count}</span></div>
  </div>
  <button id="refresh-btn" class="refresh-btn" type="button">⟳ Refresh now</button>
</div>

<div class="layout">
  <div class="grid" id="grid">
{cards_html}
  </div>
  <div class="sidebar">
    <h2>Top stories</h2>
{sidebar_html}
  </div>
</div>

<script>
  document.querySelectorAll(".pill").forEach(function (pill) {{
    pill.addEventListener("click", function () {{
      document.querySelectorAll(".pill").forEach(function (p) {{ p.classList.remove("active"); }});
      pill.classList.add("active");
      var filter = pill.getAttribute("data-filter");
      document.querySelectorAll("#grid .card").forEach(function (card) {{
        var matches = filter === "all" || card.getAttribute("data-category") === filter;
        card.classList.toggle("hidden", !matches);
      }});
    }});
  }});

  document.getElementById("refresh-btn").addEventListener("click", function () {{
    var btn = this;
    btn.disabled = true;
    btn.textContent = "⟳ Refreshing…";
    fetch("/refresh", {{ method: "POST" }})
      .then(function (resp) {{
        if (!resp.ok) throw new Error("refresh failed");
        window.location.reload();
      }})
      .catch(function () {{
        btn.disabled = false;
        btn.textContent = "⟳ Refresh failed, try again";
      }});
  }});
</script>

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
