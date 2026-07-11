import cache as cache_module


def _story(url, is_sports, fetched_at):
    return {"url": url, "is_sports": is_sports, "fetched_at": fetched_at, "title": url}


def test_update_dedupes_by_url_keeping_newest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = cache_module.StoryCache()

    store.update([_story("https://x.com/1", False, "2026-01-01T00:00:00+00:00")])
    store.update([_story("https://x.com/1", True, "2026-01-02T00:00:00+00:00")])

    stories = store.get_stories(limit=10)
    assert len(stories) == 1
    assert stories[0]["is_sports"] is True
    assert stories[0]["fetched_at"] == "2026-01-02T00:00:00+00:00"


def test_update_ranks_sports_before_general(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = cache_module.StoryCache()

    store.update([
        _story("https://x.com/general", False, "2026-01-01T00:00:00+00:00"),
        _story("https://x.com/sports", True, "2026-01-01T00:00:00+00:00"),
    ])

    stories = store.get_stories(limit=10)
    assert [s["url"] for s in stories] == ["https://x.com/sports", "https://x.com/general"]


def test_get_stories_sports_only_filters_general(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = cache_module.StoryCache()

    store.update([
        _story("https://x.com/general", False, "2026-01-01T00:00:00+00:00"),
        _story("https://x.com/sports", True, "2026-01-01T00:00:00+00:00"),
    ])

    stories = store.get_stories(limit=10, sports_only=True)
    assert [s["url"] for s in stories] == ["https://x.com/sports"]


def test_status_reports_counts_and_minimum(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = cache_module.StoryCache()

    store.update([
        _story("https://x.com/1", True, "2026-01-01T00:00:00+00:00"),
        _story("https://x.com/2", False, "2026-01-01T00:00:00+00:00"),
    ])

    status = store.status()
    assert status["total_stories"] == 2
    assert status["sports_stories"] == 1
    assert status["general_stories"] == 1
    assert status["meets_minimum"] is False
