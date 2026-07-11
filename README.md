---
title: Indian News Sports Aggregator
emoji: 🏏
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# Indian News Sports Aggregator — MCP Server

An MCP (Model Context Protocol) server that aggregates top stories from
three Indian news websites, caches at least 30 of them, refreshes the
cache on an hourly background schedule, and ranks sports stories first.
Built to run as a persistent HTTP service on Hugging Face Spaces and be
registered with Claude as a remote MCP server.

Default sources (all overridable via environment variables, no code
changes needed): **Times of India**, **Hindustan Times**, **NDTV**.

## How it works

```
scraper.py     -> fetches each site's homepage HTML, extracts headline
                   links (title + url) with a layered selector strategy
                   that degrades gracefully if a site's markup changes
classifier.py  -> labels each headline "sports" or "general", using Groq
                   (LLM) if GROQ_API_KEY is set, else a keyword/URL
                   heuristic fallback
cache.py       -> thread-safe in-memory store, merges new stories with
                   old (deduped by URL), sports-first + most-recent sort,
                   JSON snapshot on disk so a restart isn't a cold start
scheduler.py   -> APScheduler background job, refreshes the cache every
                   REFRESH_INTERVAL_MINUTES (default 60)
server.py      -> FastMCP server exposing tools over Streamable HTTP,
                   plus a plain /health endpoint
```

On startup, the server runs one synchronous fetch immediately (so the
cache is populated before the first tool call) and then starts the hourly
background job.

## MCP tools exposed

| Tool | Description |
|---|---|
| `get_top_stories(limit=30, sports_only=False)` | Cached stories, sports ranked first. Always returns >= `MIN_CACHED_STORIES` once the cache has been populated once. |
| `cache_status()` | Total/sports/general counts and last refresh timestamp. |
| `refresh_now()` | Forces an immediate fetch+classify+cache-update cycle. |
| `list_sources()` | The three configured source site names/URLs. |

Each story object looks like:

```json
{
  "title": "India beat Australia to win the series 3-1",
  "url": "https://www.ndtv.com/sports/...",
  "source": "NDTV",
  "category": "sports",
  "is_sports": true,
  "published_at": "2026-07-05T09:00:00+00:00",
  "fetched_at": "2026-07-05T09:00:00+00:00",
  "classified_by": "groq"
}
```

## 1. Local setup

```bash
cd mcp-sports-aggregator
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: set GROQ_API_KEY, and change NEWS_SITE_*_URL if you want
# different sources than the three defaults
```

Load `.env` (e.g. `export $(grep -v '^#' .env | xargs)` on Linux/macOS, or
use `python-dotenv` / your shell's preferred method), then run:

```bash
python server.py
```

You should see log lines confirming the initial fetch and that the
scheduler started. The server listens on `http://0.0.0.0:7860` by default,
with the MCP endpoint at `/mcp` (Streamable HTTP transport) and a health
check at `/health`.

## 2. Environment variables

All credentials and site URLs are configuration, never hardcoded. See
`.env.example` for the full list; the important ones:

| Variable | Required | Description |
|---|---|---|
| `NEWS_SITE_1_URL` / `_2_URL` / `_3_URL` | Yes | The three source websites to scrape. |
| `NEWS_SITE_1_NAME` / `_2_NAME` / `_3_NAME` | No | Display names for the sources (defaults provided). |
| `GROQ_API_KEY` | Recommended | Your Groq API key, from https://console.groq.com/keys. Used for LLM-based sports classification. If unset, the server automatically falls back to keyword-based classification — it keeps working, just less accurately. |
| `GROQ_MODEL` | No | Defaults to `llama-3.1-8b-instant`. Check https://console.groq.com/docs/models for currently available models and update if this one is retired. |
| `MIN_CACHED_STORIES` | No | Minimum stories guaranteed per response (default 30). |
| `REFRESH_INTERVAL_MINUTES` | No | Background refresh cadence (default 60 = hourly). |
| `PORT` | No | HF Spaces sets this automatically; defaults to 7860. |

## 3. Deploying to Hugging Face Spaces

1. Go to https://huggingface.co/new-space
2. Choose **Docker** as the Space SDK (not Gradio/Streamlit) — this repo
   is a plain Dockerized web service, which Spaces fully supports.
3. Push these files to the Space's git repo (or use the web upload UI):
   `server.py`, `config.py`, `scraper.py`, `classifier.py`, `cache.py`,
   `scheduler.py`, `requirements.txt`, `Dockerfile`.
   (Do **not** upload your `.env` file — use Secrets instead, next step.)
4. In the Space's **Settings → Variables and secrets**, add:
   - Secret: `GROQ_API_KEY` = your Groq key
   - Variables (or secrets, your preference): `NEWS_SITE_1_URL`,
     `NEWS_SITE_2_URL`, `NEWS_SITE_3_URL` (and the `_NAME` variants if you
     want custom labels), plus any of the optional tuning vars above.
5. Hugging Face will build the Dockerfile and start the container. Spaces
   automatically routes port 7860 (already set in the Dockerfile) to your
   public Space URL, e.g. `https://<your-username>-<space-name>.hf.space`.
6. Confirm it's alive: `curl https://<your-space-url>/health` should
   return `{"ok": true, "cache": {...}}`.

**Free-tier note:** free CPU Spaces sleep after a period of inactivity and
cold-start on the next request. This server's disk snapshot
(`cache_snapshot.json`) means a cold start still serves the last known
good cache immediately, while a fresh fetch runs in the background. If you
need the hourly schedule to keep firing even with no incoming traffic,
upgrade to a Space with "always on" (a paid tier), since free Spaces
suspend their process (and the APScheduler job with it) while asleep.

## 4. Registering with Claude

Once deployed, register the remote MCP server with Claude Code / the
Claude Desktop app's MCP settings, pointing at the Space's Streamable HTTP
endpoint:

```bash
claude mcp add --transport http indian-sports-news https://<your-space-url>/mcp
```

Or in Claude Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "indian-sports-news": {
      "url": "https://<your-space-url>/mcp",
      "transport": "http"
    }
  }
}
```

Then in a Claude conversation:

> "Use the indian-sports-news server to get today's top sports stories."

Claude will call `get_top_stories`, which returns the cached, sports-first
ranked list — no live scraping happens on the request path, so responses
are fast regardless of how slow the source sites are.

## 5. Notes on scraping resilience

News-site homepage markup changes over time. `scraper.py` tries a list of
common headline selectors first (`h1/h2/h3 > a`, `article a`, common
`.title`/`.story`/`.listing` classes) and tops up with a generic
"any same-domain link with headline-length text" fallback if too few
results were found. If a site heavily restructures its homepage, check
`CANDIDATE_SELECTORS` in `scraper.py` and add a selector matching the new
markup — no other code needs to change. Adding a fourth or replacement
site later is just a URL/name env var change if you're satisfied with the
generic pass, or an additional site config plus 1-2 selectors if not.
