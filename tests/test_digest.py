from datetime import datetime, timezone

from app.digest import build_digest, render_html, telegram_messages
from app.models import Keyword, NewsItem
from app.notifiers import feishu_body, feishu_sign, serverchan_form, wecom_body
from app.prefs import default_preferences


def test_digest_limits_and_escapes():
    prefs = default_preferences()
    prefs.keywords = [Keyword("Rust", 2)]
    prefs.items_per_digest = 1
    now = datetime(2026, 11, 11, 0, 30, tzinfo=timezone.utc)
    digest = build_digest(
        [
            NewsItem(source="hackernews", external_id="1", title="Rust <compiler>", url="https://example.com/rust?a=1&b=2", popularity=10),
            NewsItem(source="hackernews", external_id="2", title="Other", url="https://example.com/other", popularity=99),
        ],
        prefs,
        now=now,
    )
    assert digest.title == "科技早报 2026-11-11"
    assert len(digest.entries) == 1
    assert digest.entries[0].title.startswith("Rust")
    html = render_html(digest)
    assert "<compiler>" not in html
    assert "&lt;compiler&gt;" in html
    assert "a=1&amp;b=2" in html
    telegram = "\n".join(telegram_messages(digest))
    assert "<b>科技早报" in telegram
    assert "<compiler>" not in telegram
    assert serverchan_form(digest)["title"].startswith("科技早报")
    assert wecom_body(digest)["msgtype"] == "markdown"
    body = feishu_body(digest, secret="test-secret", timestamp="1700000000")
    assert body["sign"] == feishu_sign("1700000000", "test-secret")
    assert body["sign"] == "mbm4Y4oluIPQ00qlBIhX8vAZ0EKv3nw0LuTb91jPL84="
    assert "sign" not in feishu_body(digest)
