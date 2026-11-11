import re
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import NewsItem


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "news.db"))
    monkeypatch.setenv("ADMIN_PASSWORD", "test-pass")
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, html
    return match.group(1)


def test_health_and_settings_require_login(client):
    assert client.get("/health").json() == {"ok": True}
    home = client.get("/")
    assert home.status_code == 200
    assert "还没有抓取过" in home.text
    denied = client.get("/settings", follow_redirects=False)
    assert denied.status_code == 303
    assert denied.headers["location"].startswith("/login")


def test_login_save_preferences_and_ranked_home(client):
    page = client.get("/login?next=/settings")
    bad = client.post(
        "/login",
        data={"password": "nope", "csrf": _csrf(page.text), "next": "/settings"},
        follow_redirects=False,
    )
    assert bad.status_code == 401
    ok = client.post(
        "/login",
        data={"password": "test-pass", "csrf": _csrf(bad.text), "next": "/settings"},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    settings = client.get("/settings")
    assert settings.status_code == 200
    assert "关键词" in settings.text
    saved = client.post(
        "/settings",
        data={
            "csrf": _csrf(settings.text),
            "keywords": "Rust:2",
            "blocked": "招聘",
            "languages": "",
            "rss_feeds": "",
            "sources": ["hackernews", "github", "v2ex"],
            "items_per_digest": "10",
            "digest_hour": "8",
            "digest_minute": "0",
            "timezone": "Asia/Shanghai",
            "digest_window_hours": "36",
            "action": "save",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    client.app.state.db.upsert_items(
        [
            NewsItem(
                source="hackernews",
                external_id="1",
                title="Rust compiler notes",
                url="https://example.com/rust",
                popularity=10,
                published_at=datetime.now(timezone.utc),
            ),
            NewsItem(
                source="hackernews",
                external_id="2",
                title="Email tips",
                url="https://example.com/email",
                popularity=5000,
                published_at=datetime.now(timezone.utc),
            ),
            NewsItem(
                source="v2ex",
                external_id="3",
                title="校园招聘开始了",
                url="https://example.com/jobs",
                popularity=8000,
                published_at=datetime.now(timezone.utc),
            ),
        ]
    )
    home = client.get("/")
    assert home.status_code == 200
    assert home.text.find("Rust compiler notes") < home.text.find("Email tips")
    assert "校园招聘" not in home.text
    assert "今日技术简报" in home.text
    assert "展开看点" in home.text
    filtered = client.get("/?source=hackernews&q=Email")
    assert ">Email tips</a>" in filtered.text
    assert ">Rust compiler notes</a>" not in filtered.text
    detail = client.get("/items/1")
    assert detail.status_code == 200
    assert "摘录" in detail.text
