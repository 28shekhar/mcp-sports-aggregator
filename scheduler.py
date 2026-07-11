"""
Background job that refreshes the story cache on a schedule (default:
hourly) using APScheduler. A synchronous refresh is also expected to be
triggered once at process startup (see server.py) so the cache is
populated before the first MCP tool call, rather than waiting for the
first scheduled tick.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from cache import story_cache
from classifier import classify_stories
from config import settings
from scraper import fetch_all_sites

logger = logging.getLogger("scheduler")

_scheduler: BackgroundScheduler | None = None


def refresh_cache() -> dict:
    """Fetch fresh stories from all three sites, classify, and update the cache.

    Safe to call directly (e.g. from a manual-refresh MCP tool) or from the
    scheduled job — it never raises; failures are logged and the previous
    cache contents are simply retained.
    """
    try:
        raw_stories = fetch_all_sites()
        classified = classify_stories(raw_stories)
        story_cache.update(classified)
        return story_cache.status()
    except Exception:
        logger.exception("Cache refresh failed")
        return story_cache.status()


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        refresh_cache,
        trigger="interval",
        minutes=settings.refresh_interval_minutes,
        id="refresh_story_cache",
        next_run_time=None,  # first run is triggered manually at startup
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info(
        "Scheduler started: refreshing every %d minute(s)",
        settings.refresh_interval_minutes,
    )
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
