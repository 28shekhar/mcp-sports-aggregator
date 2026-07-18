from datetime import datetime, timedelta, timezone

from server import _fetched_within_last_24h, _select_display_items


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).isoformat()


def _story(hours_ago: float) -> dict:
    return {"title": f"story-{hours_ago}h", "fetched_at": _iso(timedelta(hours=hours_ago))}


def test_fetched_within_last_24h_true_for_recent_story():
    story = {"fetched_at": _iso(timedelta(hours=2))}
    assert _fetched_within_last_24h(story) is True


def test_fetched_within_last_24h_false_for_stale_story():
    story = {"fetched_at": _iso(timedelta(hours=25))}
    assert _fetched_within_last_24h(story) is False


def test_fetched_within_last_24h_false_when_missing():
    assert _fetched_within_last_24h({}) is False


def test_fetched_within_last_24h_false_for_invalid_timestamp():
    assert _fetched_within_last_24h({"fetched_at": "not-a-date"}) is False


def test_select_display_items_prefers_recent_stories():
    items = [_story(2), _story(30)]
    selected, showing_stale = _select_display_items(items)
    assert selected == [items[0]]
    assert showing_stale is False


def test_select_display_items_falls_back_to_stale_when_nothing_recent():
    items = [_story(30), _story(48)]
    selected, showing_stale = _select_display_items(items)
    assert selected == items
    assert showing_stale is True


def test_select_display_items_empty_cache_stays_empty():
    selected, showing_stale = _select_display_items([])
    assert selected == []
    assert showing_stale is False
