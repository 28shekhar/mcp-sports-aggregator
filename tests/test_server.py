from datetime import datetime, timedelta, timezone

from server import _fetched_within_last_24h


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).isoformat()


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
