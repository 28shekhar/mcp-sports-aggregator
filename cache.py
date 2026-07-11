"""
Thread-safe in-memory story cache with sports-first ranking.

Design goals:
- Every read returns at least `settings.min_cached_stories` stories
  whenever the cache has ever been successfully populated at least once.
- Sports stories are always sorted ahead of non-sports stories; within
  each group, newest-fetched stories come first.
- New fetches are merged with (not simply replacing) the previous cache,
  deduped by URL, so a transient scrape failure on one site doesn't shrink
  the cache below the minimum. The merged list is capped at
  `settings.max_cached_stories` to bound memory use.
- A JSON snapshot is written to disk after every update and loaded on
  startup, so a restart (e.g. HF Spaces waking from sleep) has data
  immediately instead of an empty cache until the first scheduled run.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone

from config import settings

logger = logging.getLogger("cache")


class StoryCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._stories: list[dict] = []
        self._last_updated: str | None = None
        self._load_snapshot()

    # ---- persistence ----
    def _load_snapshot(self):
        path = settings.cache_snapshot_path
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._stories = data.get("stories", [])
                self._last_updated = data.get("last_updated")
                logger.info(
                    "Loaded %d stories from snapshot (last_updated=%s)",
                    len(self._stories), self._last_updated,
                )
            except Exception:
                logger.exception("Failed to load cache snapshot at %s", path)

    def _save_snapshot(self):
        path = settings.cache_snapshot_path
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {"stories": self._stories, "last_updated": self._last_updated},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception:
            logger.exception("Failed to write cache snapshot at %s", path)

    # ---- core ranking ----
    @staticmethod
    def _sort_key(story: dict):
        # Sports first (False sorts before True with `not`), then recency.
        return (not story.get("is_sports", False), story.get("fetched_at", ""))

    def update(self, new_stories: list[dict]):
        """Merge freshly fetched+classified stories into the cache."""
        with self._lock:
            merged_by_url = {s["url"]: s for s in self._stories}
            for story in new_stories:
                merged_by_url[story["url"]] = story  # newer data wins

            merged = list(merged_by_url.values())
            merged.sort(key=self._sort_key)
            merged = merged[: settings.max_cached_stories]

            self._stories = merged
            self._last_updated = datetime.now(timezone.utc).isoformat()
            self._save_snapshot()

            sports_count = sum(1 for s in merged if s.get("is_sports"))
            logger.info(
                "Cache updated: %d total stories (%d sports, %d general)",
                len(merged), sports_count, len(merged) - sports_count,
            )

    def get_stories(self, limit: int | None = None, sports_only: bool = False) -> list[dict]:
        with self._lock:
            stories = list(self._stories)

        if sports_only:
            stories = [s for s in stories if s.get("is_sports")]

        limit = limit or settings.min_cached_stories
        return stories[:limit]

    def status(self) -> dict:
        with self._lock:
            total = len(self._stories)
            sports = sum(1 for s in self._stories if s.get("is_sports"))
            return {
                "total_stories": total,
                "sports_stories": sports,
                "general_stories": total - sports,
                "last_updated": self._last_updated,
                "min_required": settings.min_cached_stories,
                "meets_minimum": total >= settings.min_cached_stories,
            }


story_cache = StoryCache()
