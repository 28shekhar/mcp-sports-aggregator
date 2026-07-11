"""
Generic, resilient headline scraper for the three configured news sites.

News-site markup changes often, so instead of hardcoding brittle CSS
selectors for each of the three sites, this module uses a layered strategy:

 1. Try a set of common "headline" selectors used by most Indian news
    portals (Times of India, Hindustan Times, NDTV and similar sites all
    render top stories as `<a>` tags nested in headline/heading elements).
 2. Fall back to a generic heuristic pass over every `<a>` tag on the page,
    filtering out navigation/boilerplate links and keeping ones that look
    like real headlines (sufficient text length, not a nav/utility link).

This keeps the scraper working even if a site's exact CSS classes change,
and makes it trivial to point at a completely different site by only
changing the URL in the environment variables — no selector code changes
required.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import SiteConfig, settings

logger = logging.getLogger("scraper")

# Selectors tried in priority order. These cover the common markup patterns
# used by large Indian news portals (headline anchors inside h1-h4 tags,
# "listing"/"card"/"story" style wrapper classes, and <article> tags).
CANDIDATE_SELECTORS = [
    "h1 a[href]",
    "h2 a[href]",
    "h3 a[href]",
    "article a[href]",
    "figure a[href]",
    "a.title[href]",
    "a[data-title][href]",
    ".top-story a[href]",
    ".listing a[href]",
    ".story a[href]",
]

# Path/keyword hints that let us guess a story's category straight from its
# URL, before any LLM/keyword classification runs. This also lets us
# recognize a site's dedicated sports section, if the homepage links there.
SPORTS_URL_HINTS = (
    "/sport", "/cricket", "/football", "/tennis", "/hockey", "/olympic",
    "/ipl", "/isl", "/kabaddi", "/badminton", "/athletics", "/wwe",
    "/formula1", "/f1", "/chess", "-cricket-", "-football-",
)

# Links that are almost never real headlines (nav, utility, legal, etc.)
BOILERPLATE_PATTERNS = re.compile(
    r"(privacy|terms|contact|advertise|about-us|subscribe|newsletter|"
    r"sitemap|login|sign-?in|sign-?up|cookie|rss|app-download|feedback|"
    r"careers|disclaimer)",
    re.IGNORECASE,
)


def _looks_like_headline(text: str) -> bool:
    text = text.strip()
    if len(text) < 20 or len(text) > 220:
        return False
    # Nav items are usually short single words/phrases without spaces info
    if text.count(" ") < 2:
        return False
    return True


def _guess_category(url: str) -> str | None:
    lowered = url.lower()
    if any(hint in lowered for hint in SPORTS_URL_HINTS):
        return "sports"
    return None


def fetch_html(site: SiteConfig) -> str | None:
    try:
        resp = requests.get(
            site.url,
            headers={"User-Agent": settings.user_agent, "Accept-Language": "en-IN,en;q=0.9"},
            timeout=settings.request_timeout_seconds,
        )
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        logger.warning("Failed to fetch %s (%s): %s", site.name, site.url, exc)
        return None


def _extract_with_selectors(soup: BeautifulSoup, base_url: str) -> list[dict]:
    seen_urls = set()
    stories = []
    for selector in CANDIDATE_SELECTORS:
        for a in soup.select(selector):
            href = a.get("href")
            text = a.get_text(" ", strip=True)
            if not href or not text:
                continue
            if not _looks_like_headline(text):
                continue
            full_url = urljoin(base_url, href)
            if full_url in seen_urls:
                continue
            if BOILERPLATE_PATTERNS.search(full_url) or BOILERPLATE_PATTERNS.search(text):
                continue
            seen_urls.add(full_url)
            stories.append({"title": text, "url": full_url})
    return stories


def _extract_generic_fallback(soup: BeautifulSoup, base_url: str) -> list[dict]:
    seen_urls = set()
    stories = []
    domain = urlparse(base_url).netloc
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = a["href"]
        if not _looks_like_headline(text):
            continue
        full_url = urljoin(base_url, href)
        if urlparse(full_url).netloc != domain:
            continue  # skip off-site/ad links
        if full_url in seen_urls:
            continue
        if BOILERPLATE_PATTERNS.search(full_url) or BOILERPLATE_PATTERNS.search(text):
            continue
        seen_urls.add(full_url)
        stories.append({"title": text, "url": full_url})
    return stories


def parse_stories(html: str, site: SiteConfig, limit: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    stories = _extract_with_selectors(soup, site.url)
    if len(stories) < max(5, limit // 3):
        # Selector pass found too little — top up with the generic pass.
        existing = {s["url"] for s in stories}
        for s in _extract_generic_fallback(soup, site.url):
            if s["url"] not in existing:
                stories.append(s)
                existing.add(s["url"])

    now = datetime.now(timezone.utc).isoformat()
    result = []
    for s in stories[:limit]:
        result.append({
            "title": s["title"],
            "url": s["url"],
            "source": site.name,
            "published_at": now,  # homepages rarely expose reliable timestamps
            "fetched_at": now,
            "category_hint": _guess_category(s["url"]),
        })
    return result


def fetch_site_stories(site: SiteConfig, limit: int | None = None) -> list[dict]:
    limit = limit or settings.stories_per_site_fetch
    html = fetch_html(site)
    if not html:
        return []
    try:
        return parse_stories(html, site, limit)
    except Exception:
        logger.exception("Failed to parse stories for %s", site.name)
        return []


def fetch_all_sites() -> list[dict]:
    """Fetch and parse stories from all three configured sites.

    A failure on one site never blocks the others — each site is fetched
    independently and errors are logged, not raised.
    """
    all_stories: list[dict] = []
    for site in settings.sites:
        site_stories = fetch_site_stories(site)
        logger.info("Fetched %d stories from %s", len(site_stories), site.name)
        all_stories.extend(site_stories)
    return all_stories
