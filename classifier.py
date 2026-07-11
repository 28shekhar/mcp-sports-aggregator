"""
Sports-vs-other classification for scraped headlines.

Two layers, in priority order:

1. Groq LLM classification (fast batched call to Groq's OpenAI-compatible
   chat completion endpoint) - used when GROQ_API_KEY is configured. This
   is the "category detection" logic the aggregator relies on primarily,
   since a homepage headline like "Rohit Sharma steps down as captain"
   needs real-world knowledge to recognize as sports.
2. A keyword/URL heuristic fallback - always available, requires no
   credentials, and is used automatically if the Groq call fails, times
   out, or no API key is configured. This guarantees the server keeps
   working (with degraded category accuracy) even without the key.

The Groq API key is read only from the environment (config.settings) and
is never hardcoded.
"""
from __future__ import annotations

import json
import logging
import re

import requests

from config import settings

logger = logging.getLogger("classifier")

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"

SPORTS_KEYWORDS = re.compile(
    r"\b("
    r"cricket|football|soccer|hockey|tennis|badminton|kabaddi|olympics?|"
    r"paralympics?|wrestl\w*|boxing|athletics|marathon|chess|wwe|f1|"
    r"formula\s?1|motogp|golf|rugby|volleyball|basketball|kho-?kho|"
    r"ipl|isl|bcci|icc|fifa|uefa|premier\s?league|world\s?cup|"
    r"test\s?match|odi|t20|wicket|century|innings|batsman|bowler|all-?rounder|"
    r"striker|midfielder|goalkeeper|medal|gold\s?medal|tournament|"
    r"championship|grand\s?slam|wimbledon|us\s?open|australian\s?open|"
    r"french\s?open|asian\s?games|commonwealth\s?games|"
    r"rohit\s?sharma|virat\s?kohli|ms\s?dhoni|neeraj\s?chopra|"
    r"pv\s?sindhu|sachin\s?tendulkar"
    r")\b",
    re.IGNORECASE,
)


def keyword_is_sports(title: str, url: str, category_hint: str | None) -> bool:
    if category_hint == "sports":
        return True
    return bool(SPORTS_KEYWORDS.search(title) or SPORTS_KEYWORDS.search(url))


def _keyword_classify(stories: list[dict]) -> list[dict]:
    for story in stories:
        story["is_sports"] = keyword_is_sports(
            story["title"], story["url"], story.get("category_hint")
        )
        story["category"] = "sports" if story["is_sports"] else "general"
        story.setdefault("classified_by", "keyword")
    return stories


def _groq_classify(stories: list[dict]) -> list[dict] | None:
    if not settings.groq_enabled or not settings.groq_api_key:
        return None

    # Batch headlines into one prompt to minimize API calls.
    numbered = "\n".join(f"{i+1}. {s['title']}" for i, s in enumerate(stories))
    prompt = (
        "You are a news categorization assistant. For each numbered headline "
        "below, decide if it is primarily about SPORTS (any game, athlete, "
        "match, tournament, league, or sporting event) or OTHER (politics, "
        "business, entertainment, weather, general news, etc).\n\n"
        f"{numbered}\n\n"
        "Respond ONLY with a JSON array of the same length, where each "
        'element is either "sports" or "other", in the same order as the '
        'headlines. Example: ["sports", "other", "sports"]'
    )

    try:
        resp = requests.post(
            GROQ_CHAT_COMPLETIONS_URL,
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.groq_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 2048,
            },
            timeout=settings.request_timeout_seconds,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

        match = re.search(r"\[.*\]", content, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON array found in Groq response: {content!r}")
        labels = json.loads(match.group(0))

        if len(labels) != len(stories):
            raise ValueError(
                f"Groq returned {len(labels)} labels for {len(stories)} stories"
            )

        for story, label in zip(stories, labels):
            is_sports = str(label).strip().lower() == "sports"
            story["is_sports"] = is_sports
            story["category"] = "sports" if is_sports else "general"
            story["classified_by"] = "groq"
        return stories
    except Exception as exc:
        logger.warning("Groq classification failed, falling back to keywords: %s", exc)
        return None


def classify_stories(stories: list[dict], batch_size: int = 30) -> list[dict]:
    """Classify every story as sports/general, mutating and returning the list."""
    if not stories:
        return stories

    remaining = stories
    classified: list[dict] = []
    while remaining:
        batch, remaining = remaining[:batch_size], remaining[batch_size:]
        result = _groq_classify(batch)
        if result is None:
            result = _keyword_classify(batch)
        classified.extend(result)
    return classified
