import json
from pathlib import Path

import pytest

from app.fetchers.github import github_language_slug, parse_github_trending, trending_url
from app.fetchers.hackernews import parse_hn_items
from app.fetchers.juejin import parse_juejin
from app.fetchers.producthunt import parse_producthunt
from app.fetchers.reddit import parse_reddit_atom
from app.fetchers.rss import parse_feed
from app.fetchers.sspai import parse_sspai
from app.fetchers.v2ex import parse_v2ex

FIXTURES = Path(__file__).parent / "fixtures"


def test_github_recorded_fixture():
    items = parse_github_trending((FIXTURES / "github_trending.html").read_text(encoding="utf-8"))
    assert [item.external_id for item in items] == ["meta/astryx", "anthropics/skills"]
    first = items[0]
    assert first.title == "meta/astryx"
    assert first.url == "https://github.com/meta/astryx"
    assert first.language == "TypeScript"
    assert first.popularity == 3108
    assert first.extra["stars"] == 23836
    assert "design system" in first.summary
    assert items[1].language == "Python"
    assert items[1].popularity == 1679


def test_github_minimal_markup_falls_back_to_total_stars():
    html = """
    <article class="Box-row">
      <h2><a href="/octocat/hello">octocat / hello</a></h2>
      <a href="/octocat/hello/stargazers">1,001</a>
    </article>
    <article class="Box-row">
      <h2><a href="/login">skip</a></h2>
    </article>
    """
    items = parse_github_trending(html)
    assert len(items) == 1
    assert items[0].external_id == "octocat/hello"
    assert items[0].popularity == 1001
    assert items[0].language == ""
    assert parse_github_trending("<html></html>") == []


def test_github_language_slug():
    assert github_language_slug("Objective C") == "objective-c"
    assert github_language_slug("golang") == "go"
    assert "c%23" in trending_url("c#")


def test_hackernews_fixture_and_skips():
    recorded = json.loads((FIXTURES / "hn_items.json").read_text(encoding="utf-8"))
    items = parse_hn_items(recorded)
    assert items[0].title.startswith("Protecting SSH")
    assert items[0].url.startswith("https://gatezh.com/")
    assert items[0].popularity > 0
    assert items[0].author
    extra = parse_hn_items(
        [
            {"id": 1, "type": "story", "title": "Ask HN", "text": "<p>Hello</p>", "score": 3, "time": 1700000000},
            {"id": 2, "type": "job", "title": "Hiring", "score": 1},
            {"id": 3, "type": "story", "title": "Gone", "deleted": True, "score": 1},
        ]
    )
    assert len(extra) == 1
    assert extra[0].url.endswith("item?id=1")
    assert "Hello" in extra[0].summary


def test_v2ex_fixture():
    items = parse_v2ex(json.loads((FIXTURES / "v2ex_hot.json").read_text(encoding="utf-8")))
    assert items[0].external_id == "1256055"
    assert items[0].url == "https://www.v2ex.com/t/1256055"
    assert items[0].popularity == 268
    assert items[0].summary.startswith("[生活]")
    assert items[0].author == "6581"
    with pytest.raises(ValueError):
        parse_v2ex({"message": "rate limited"})


def test_juejin_fixture():
    items = parse_juejin(json.loads((FIXTURES / "juejin_rank.json").read_text(encoding="utf-8")))
    assert items[0].external_id == "7705987138957328427"
    assert items[0].url.endswith("/post/7705987138957328427")
    assert items[0].popularity == 3510
    assert items[0].author == "XCaptain"
    assert items[0].published_at is None
    with pytest.raises(ValueError):
        parse_juejin({"err_no": 2, "err_msg": "请求路由不存在"})


def test_reddit_atom_uses_external_link():
    items = parse_reddit_atom((FIXTURES / "reddit_programming.atom").read_text(encoding="utf-8"))
    assert len(items) == 2
    assert items[0].title == "Announcing .NET 11"
    assert items[0].url == "https://devblogs.microsoft.com/dotnet/announcing-dotnet-11/"
    assert "reddit.com" not in items[0].url
    assert items[0].summary == ""
    assert items[1].url.startswith("https://ramsayleung.github.io/")


def test_sspai_fixture():
    items = parse_sspai(json.loads((FIXTURES / "sspai_index.json").read_text(encoding="utf-8")))
    assert items[0].title.startswith("从优胜美地")
    assert items[0].url == "https://sspai.com/post/118175"
    assert items[0].author == "StephenFang"
    assert items[0].popularity == 8
    assert "加州" in items[0].summary


def test_producthunt_atom():
    items = parse_producthunt((FIXTURES / "producthunt.atom").read_text(encoding="utf-8"))
    assert items[0].title == "Kippy AI"
    assert items[0].url == "https://www.producthunt.com/products/kippy-ai"
    assert items[0].summary == "Learn languages while having fun!"
    assert items[0].author == "Steve Olesansky"
    assert items[0].popularity == 2


def test_infoq_rss_fixture():
    items = parse_feed(
        (FIXTURES / "infoq.xml").read_text(encoding="utf-8"),
        source="rss:test",
        feed_name="InfoQ 中文",
        feed_url="https://www.infoq.cn/feed",
    )
    assert len(items) == 2
    assert items[0].title.startswith("阿里云")
    assert items[0].author == "凌敏"
    assert items[0].summary == ""
    assert "xCQx0qBofJYfBdVrxVxt" in items[0].url
    assert items[0].extra["feed_name"] == "InfoQ 中文"
    assert items[0].published_at is not None
    assert items[0].published_at.year == 2026
