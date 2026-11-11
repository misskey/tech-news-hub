"""少数派首页文章。"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.fetchers.base import FetchOutcome
from app.models import NewsItem, Preferences

INDEX_URL = "https://sspai.com/api/v1/article/index/page/get?limit=20&offset=0"


def parse_sspai(payload: object) -> list[NewsItem]:
    if not isinstance(payload, dict):
        raise ValueError("少数派响应不是 JSON 对象")
    if payload.get("error") not in (0, None):
        raise ValueError(str(payload.get("msg") or "少数派接口返回错误"))
    data = payload.get("data") or []
    if not isinstance(data, list):
        raise ValueError("少数派响应缺少文章列表")
    items: list[NewsItem] = []
    for article in data:
        if not isinstance(article, dict):
            continue
        article_id = article.get("id")
        title = str(article.get("title") or "").strip()
        if article_id is None or not title:
            continue
        external_id = str(article_id)
        published = None
        if article.get("released_time"):
            try:
                published = datetime.fromtimestamp(int(article["released_time"]), timezone.utc)
            except (TypeError, ValueError, OSError):
                published = None
        author = article.get("author") or {}
        items.append(
            NewsItem(
                source="sspai",
                external_id=external_id,
                title=title,
                url=f"https://sspai.com/post/{external_id}",
                summary=str(article.get("summary") or "").strip()[:500],
                author=str(author.get("nickname") or "") if isinstance(author, dict) else "",
                popularity=float(article.get("like_count") or 0),
                published_at=published,
                extra={"comments": article.get("comment_count") or 0},
            )
        )
    return items


class SspaiFetcher:
    source_id = "sspai"
    label = "少数派"

    async def run(self, client: httpx.AsyncClient, prefs: Preferences) -> FetchOutcome:
        del prefs
        response = await client.get(INDEX_URL)
        response.raise_for_status()
        items = parse_sspai(response.json())
        if not items:
            return FetchOutcome(error="少数派没有返回文章")
        return FetchOutcome(items=items)
