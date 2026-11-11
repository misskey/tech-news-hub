import json
from datetime import datetime, timezone

from app.db import Database
from app.digest import build_digest, render_markdown
from app.models import Briefing, ItemSummary, Keyword, NewsItem, ScoredItem
from app.prefs import default_preferences
from app.summary import assemble_briefing, ensure_briefing, ensure_summaries, extractive_summary


class FakeSettings:
    openai_api_key = "sk-test"
    openai_base_url = "https://example.invalid/v1"
    openai_model = "fake-model"


class FakeChat:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = 0
        self.model = "fake-model"

    def complete(self, messages):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        text = messages[-1]["content"]
        if text.startswith("今日共"):
            return json.dumps({"overview": "今天值得看的是新发布的工具。", "highlights": ["一个新的编译器发布了"]}, ensure_ascii=False)
        return json.dumps(self.payload or {
            "items": [{"index": 0, "short": "这是中文短摘要。", "long": "这是更长的一段中文说明。", "takeaways": ["Rust"]}]
        }, ensure_ascii=False)


def _item(**kwargs) -> NewsItem:
    payload = {
        "source": "hackernews",
        "external_id": "1",
        "title": "Announcing Rust 1.80",
        "url": "https://example.com/rust",
        "summary": "The Rust compiler release is faster.",
        "popularity": 20,
    }
    payload.update(kwargs)
    return NewsItem(**payload)


def test_extractive_chinese_snippet_and_takeaways():
    summary = extractive_summary(
        _item(
            source="juejin",
            external_id="j1",
            title="开源了一个配置库",
            summary="这是一个新的 Rust 库。它用来处理配置。第二句说明用法。",
        )
    )
    assert summary.provider == "extractive"
    assert summary.short.startswith("这是一个新的 Rust 库")
    assert "Rust" in summary.takeaways
    assert len(summary.long) >= len(summary.short)


def test_extractive_english_keeps_title_and_quote():
    summary = extractive_summary(_item())
    assert "Announcing Rust 1.80" in summary.short
    assert "摘录" in summary.short
    assert "Rust" in summary.takeaways
    assert "新发布" in summary.short


def test_extractive_without_body_is_still_readable():
    summary = extractive_summary(_item(title="Only a title", summary=""))
    assert "没有附带简介" in summary.short
    assert summary.long == summary.short


def test_briefing_groups_themes_and_names_items():
    prefs = default_preferences()
    prefs.keywords = [Keyword("Rust", 2)]
    item = _item()
    scored = ScoredItem(item, 200, 200, 0, 3, ["Rust"])
    summary = extractive_summary(item)
    briefing = assemble_briefing([scored], {(item.source, item.external_id): summary})
    assert "今天有 1 条" in briefing.overview
    assert "Rust" in briefing.overview
    assert any("Announcing Rust 1.80" in line for line in briefing.highlights)
    digest = build_digest(
        [item],
        prefs,
        now=datetime(2026, 11, 11, 1, tzinfo=timezone.utc),
        summaries={(item.source, item.external_id): summary},
        briefing=Briefing("今天先看发布。", ["新发布：Hacker News《Announcing Rust 1.80》"]),
    )
    text = render_markdown(digest)
    assert "今日新技术看点" in text
    assert "今天先看发布" in text
    assert summary.short in text


def test_summary_cache_and_llm_failure(tmp_path):
    db = Database(tmp_path / "news.db")
    db.init()
    prefs = default_preferences()
    prefs.llm_summaries = True
    item = _item()
    chat = FakeChat()
    settings = FakeSettings()
    moment = datetime(2026, 11, 11, 2, tzinfo=timezone.utc)

    first = ensure_summaries(db, [item], prefs, settings, chat=chat)
    assert first[(item.source, item.external_id)].provider == "llm"
    assert first[(item.source, item.external_id)].short == "这是中文短摘要。"
    assert chat.calls == 1
    again = ensure_summaries(db, [item], prefs, settings, chat=chat)
    assert again[(item.source, item.external_id)].short == "这是中文短摘要。"
    assert chat.calls == 1

    briefing = ensure_briefing(
        db,
        [ScoredItem(item, 10, 0, 0, 3, [])],
        first,
        prefs,
        settings,
        now=moment,
        chat=chat,
    )
    assert briefing.provider == "llm"
    assert "新发布" in briefing.overview or "编译器" in briefing.overview
    calls_after_briefing = chat.calls
    ensure_briefing(
        db,
        [ScoredItem(item, 10, 0, 0, 3, [])],
        first,
        prefs,
        settings,
        now=moment,
        chat=chat,
    )
    assert chat.calls == calls_after_briefing

    changed = _item(title="Announcing Rust 1.81")
    ensure_summaries(db, [changed], prefs, settings, chat=chat)
    assert chat.calls == calls_after_briefing + 1

    boom = FakeChat(error="down")
    fallback = ensure_summaries(db, [_item(external_id="2", title="Other tool")], prefs, settings, chat=boom)
    assert fallback[("hackernews", "2")].provider == "extractive"
    brief = ensure_briefing(
        db,
        [ScoredItem(_item(external_id="2", title="Other tool"), 1, 0, 0, 1, [])],
        fallback,
        prefs,
        settings,
        now=moment,
        chat=boom,
    )
    assert brief.provider == "extractive"
    assert "今天有" in brief.overview
