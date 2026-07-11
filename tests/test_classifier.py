from classifier import classify_category, _keyword_classify


def test_classify_category_matches_cricket_keyword():
    assert classify_category("India win the World Cup ODI", "https://x.com/a", None) == "cricket"


def test_classify_category_matches_cricket_player_name():
    assert classify_category("Rohit Sharma steps down as captain", "https://x.com/b", None) == "cricket"


def test_classify_category_matches_cricket_url_when_title_has_no_keyword():
    assert classify_category("Big win for the home team", "https://x.com/cricket/story", None) == "cricket"


def test_classify_category_matches_football_keyword():
    assert classify_category("Messi scores winning goal in final", "https://x.com/c", None) == "football"


def test_classify_category_matches_tennis_keyword():
    assert classify_category("Djokovic advances to Wimbledon final", "https://x.com/d", None) == "tennis"


def test_classify_category_matches_tennis_url_when_title_has_no_keyword():
    assert classify_category("Big win in straight sets", "https://x.com/tennis/story", None) == "tennis"


def test_classify_category_general_for_unrelated_headline():
    assert classify_category("Budget session begins in parliament", "https://x.com/politics", None) == "general"


def test_classify_category_respects_cricket_hint():
    assert classify_category("Nothing sporty here at all", "https://x.com/other", "cricket") == "cricket"


def test_classify_category_respects_football_hint():
    assert classify_category("Nothing sporty here at all", "https://x.com/other", "football") == "football"


def test_classify_category_respects_tennis_hint():
    assert classify_category("Nothing sporty here at all", "https://x.com/other", "tennis") == "tennis"


def test_keyword_classify_sets_category_and_classified_by():
    stories = [
        {"title": "India beat Australia in thrilling ODI", "url": "https://x.com/1"},
        {"title": "Ronaldo nets a hat-trick in derby win", "url": "https://x.com/2"},
        {"title": "Nadal wins epic five-set thriller", "url": "https://x.com/3"},
        {"title": "New tax policy announced", "url": "https://x.com/4"},
    ]
    result = _keyword_classify(stories)

    assert result[0]["is_sports"] is True
    assert result[0]["category"] == "cricket"
    assert result[0]["classified_by"] == "keyword"

    assert result[1]["is_sports"] is True
    assert result[1]["category"] == "football"

    assert result[2]["is_sports"] is True
    assert result[2]["category"] == "tennis"

    assert result[3]["is_sports"] is False
    assert result[3]["category"] == "general"
