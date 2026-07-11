from classifier import keyword_is_sports, _keyword_classify


def test_keyword_is_sports_matches_known_keyword():
    assert keyword_is_sports("India win the cricket World Cup", "https://x.com/a", None)


def test_keyword_is_sports_matches_player_name():
    assert keyword_is_sports("Rohit Sharma steps down as captain", "https://x.com/b", None)


def test_keyword_is_sports_matches_url_when_title_has_no_keyword():
    assert keyword_is_sports("Big win for the home team", "https://x.com/cricket/story", None)


def test_keyword_is_sports_false_for_unrelated_headline():
    assert not keyword_is_sports("Budget session begins in parliament", "https://x.com/politics", None)


def test_keyword_is_sports_respects_category_hint():
    assert keyword_is_sports("Nothing sporty here at all", "https://x.com/other", "sports")


def test_keyword_classify_sets_category_and_classified_by():
    stories = [
        {"title": "India beat Australia in thrilling ODI", "url": "https://x.com/1"},
        {"title": "New tax policy announced", "url": "https://x.com/2"},
    ]
    result = _keyword_classify(stories)

    assert result[0]["is_sports"] is True
    assert result[0]["category"] == "sports"
    assert result[0]["classified_by"] == "keyword"

    assert result[1]["is_sports"] is False
    assert result[1]["category"] == "general"
