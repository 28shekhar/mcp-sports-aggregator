"""
Cricket/football/tennis/general classification for scraped headlines.

Two layers, in priority order:

1. Groq LLM classification (fast batched call to Groq's OpenAI-compatible
   chat completion endpoint) - used when GROQ_API_KEY is configured. This
   is the "category detection" logic the aggregator relies on primarily,
   since a homepage headline like "Rohit Sharma steps down as captain"
   needs real-world knowledge to recognize as cricket.
2. A keyword/URL heuristic fallback - always available, requires no
   credentials, and is used automatically if the Groq call fails, times
   out, or no API key is configured. This guarantees the server keeps
   working (with degraded category accuracy) even without the key.

Only cricket, football, and tennis get their own category; every other
story (other sports, general news, entertainment, etc.) is "general" -
this aggregator only tracks those three sports specifically.

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

CRICKET_KEYWORDS = re.compile(
    r"\b("
    r"cricket|ipl|bcci|icc|test\s?match|odi|t20|wicket|century|innings|"
    r"batsman|bowler|all-?rounder|"
    r"rohit\s?sharma|virat\s?kohli|ms\s?dhoni|sachin\s?tendulkar"
    r")\b",
    re.IGNORECASE,
)

FOOTBALL_KEYWORDS = re.compile(
    r"\b("
    r"football|soccer|fifa|uefa|premier\s?league|isl|champions\s?league|"
    r"la\s?liga|epl|striker|midfielder|goalkeeper|messi|ronaldo"
    r")\b",
    re.IGNORECASE,
)

TENNIS_KEYWORDS = re.compile(
    r"\b("
    r"tennis|wimbledon|us\s?open|australian\s?open|french\s?open|roland\s?garros|"
    r"grand\s?slam|atp|wta|djokovic|nadal|federer|alcaraz|sinner|"
    r"serena\s?williams"
    r")\b",
    re.IGNORECASE,
)


def classify_category(title: str, url: str, category_hint: str | None) -> str:
    if category_hint in ("cricket", "football", "tennis"):
        return category_hint
    if CRICKET_KEYWORDS.search(title) or CRICKET_KEYWORDS.search(url):
        return "cricket"
    if FOOTBALL_KEYWORDS.search(title) or FOOTBALL_KEYWORDS.search(url):
        return "football"
    if TENNIS_KEYWORDS.search(title) or TENNIS_KEYWORDS.search(url):
        return "tennis"
    return "general"


def _keyword_classify(stories: list[dict]) -> list[dict]:
    for story in stories:
        category = classify_category(
            story["title"], story["url"], story.get("category_hint")
        )
        story["category"] = category
        story["is_sports"] = category != "general"
        story.setdefault("classified_by", "keyword")
    return stories


def _groq_classify(stories: list[dict]) -> list[dict] | None:
    if not settings.groq_enabled or not settings.groq_api_key:
        return None

    # Batch headlines into one prompt to minimize API calls.
    numbered = "\n".join(f"{i+1}. {s['title']}" for i, s in enumerate(stories))
    prompt = (
        "You are a news categorization assistant. For each numbered headline "
        "below, decide if it is primarily about CRICKET, FOOTBALL/SOCCER, "
        "TENNIS, or OTHER (any other sport, politics, business, "
        "entertainment, weather, general news, etc).\n\n"
        f"{numbered}\n\n"
        "Respond ONLY with a JSON array of the same length, where each "
        'element is "cricket", "football", "tennis", or "other", in the same '
        'order as the headlines. Example: ["cricket", "other", "football"]'
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
            category = str(label).strip().lower()
            if category not in ("cricket", "football", "tennis"):
                category = "general"
            story["category"] = category
            story["is_sports"] = category != "general"
            story["classified_by"] = "groq"
        return stories
    except Exception as exc:
        logger.warning("Groq classification failed, falling back to keywords: %s", exc)
        return None


def classify_stories(stories: list[dict], batch_size: int = 30) -> list[dict]:
    """Classify every story as cricket/football/general, mutating and returning the list."""
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
