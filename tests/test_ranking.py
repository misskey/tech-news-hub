from datetime import datetime, timezone

from app.models import Keyword, NewsItem
from app.prefs import default_preferences
from app.ranking import canonical_url, keyword_in, rank_items


def make_item(**kwargs) -> NewsItem:
    payload = {
        "source": "hackernews",
        "external_id": kwargs.get("url", "1"),
        "title": "Hello",
        "url": "https://example.com/hello",
        "popularity": 10,
    }
    payload.update(kwargs)
    return NewsItem(**payload)


def make_prefs(**kwargs):
    prefs = default_preferences()
    for key, value in kwargs.items():
        setattr(prefs, key, value)
    return prefs


def test_keyword_boundaries_and_cjk():
    assert keyword_in("New AI model", "AI")
    assert not keyword_in("Email tips for teams", "AI")
    assert keyword_in("最好的开源模型", "开源")
    assert keyword_in("campus 招聘 season", "招聘")


def test_blocked_keyword_drops_item_even_if_it_matches_interest():
    prefs = make_prefs(
        keywords=[Keyword("招聘", 5)],
        blocked_keywords=["招聘"],
    )
    ranked = rank_items([make_item(title="校园招聘开始了", popularity=9999)], prefs)
    assert ranked == []


def test_keyword_weight_beats_raw_popularity_and_sums():
    prefs = make_prefs(keywords=[Keyword("Rust", 2), Keyword("LLM", 1)])
    ranked = rank_items(
        [
            make_item(title="unrelated viral post", url="https://example.com/v", popularity=100000, external_id="v"),
            make_item(title="Rust LLM weekly", url="https://example.com/r", popularity=10, external_id="r"),
        ],
        prefs,
    )
    assert [item.item.title for item in ranked][0] == "Rust LLM weekly"
    assert ranked[0].keyword_score == 300
    assert ranked[0].matched == ["Rust", "LLM"]
    assert ranked[0].score > ranked[1].score


def test_equal_keywords_use_popularity_as_tiebreak():
    prefs = make_prefs(keywords=[Keyword("AI", 1)])
    ranked = rank_items(
        [
            make_item(title="AI notes", url="https://example.com/a", popularity=10, external_id="a"),
            make_item(title="AI systems", url="https://example.com/b", popularity=1000, external_id="b"),
        ],
        prefs,
    )
    assert ranked[0].item.external_id == "b"
    assert ranked[0].keyword_score == ranked[1].keyword_score


def test_language_bonus_and_alias():
    prefs = make_prefs(keywords=[], languages=["golang"])
    ranked = rank_items(
        [
            make_item(source="github", title="A", language="Python", popularity=50, url="https://example.com/py", external_id="py"),
            make_item(source="github", title="B", language="Go", popularity=50, url="https://example.com/go", external_id="go"),
        ],
        prefs,
    )
    assert ranked[0].item.language == "Go"
    assert ranked[0].language_score == 3
    assert ranked[1].language_score == 0


def test_disabled_source_is_excluded():
    prefs = make_prefs(enabled_sources=["hackernews"])
    ranked = rank_items(
        [
            make_item(source="v2ex", title="V", url="https://example.com/v", external_id="v"),
            make_item(source="hackernews", title="H", url="https://example.com/h", external_id="h"),
        ],
        prefs,
    )
    assert [item.item.source for item in ranked] == ["hackernews"]


def test_no_keywords_ranks_by_popularity():
    prefs = make_prefs(keywords=[])
    ranked = rank_items(
        [
            make_item(title="small", popularity=3, url="https://example.com/s", external_id="s"),
            make_item(title="big", popularity=300, url="https://example.com/b", external_id="b"),
        ],
        prefs,
    )
    assert [item.item.title for item in ranked] == ["big", "small"]


def test_negative_weight_sinks_the_match():
    prefs = make_prefs(keywords=[Keyword("广告", -1)])
    ranked = rank_items(
        [
            make_item(title="软文广告", popularity=10000, url="https://example.com/ad", external_id="ad"),
            make_item(title="plain note", popularity=20, url="https://example.com/n", external_id="n"),
        ],
        prefs,
    )
    assert ranked[0].item.external_id == "n"


def test_digest_limit_and_url_dedupe():
    prefs = make_prefs(keywords=[Keyword("Rust", 2)])
    now = datetime(2026, 11, 11, tzinfo=timezone.utc)
    ranked = rank_items(
        [
            make_item(
                title="Rust release",
                url="https://www.example.com/post?utm_source=rss",
                popularity=5,
                external_id="a",
                source="reddit",
                published_at=now,
            ),
            make_item(
                title="same story mirror",
                url="https://example.com/post",
                popularity=9000,
                external_id="b",
                source="hackernews",
                published_at=now,
            ),
            make_item(title="other", url="https://example.com/other", popularity=1, external_id="c"),
        ],
        prefs,
        limit=1,
    )
    assert len(ranked) == 1
    assert ranked[0].item.external_id == "a"
    assert canonical_url("https://www.Example.com/post/?utm_source=rss") == canonical_url("https://example.com/post")
