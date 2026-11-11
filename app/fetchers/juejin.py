"""掘金综合热榜。"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.fetchers.base import FetchOutcome
from app.models import NewsItem, Preferences

RANK_URL = "https://api.juejin.cn/content_api/v1/content/article_rank?category_id=1&type=hot"


def parse_juejin(payload: object) -> list[NewsItem]:
    if not isinstance(payload, dict):
        raise ValueError("掘金响应不是 JSON 对象")
    err_no = payload.get("err_no")
    if err_no not in (0, None):
        raise ValueError(str(payload.get("err_msg") or f"掘金错误 {err_no}"))
    data = payload.get("data") or []
    if not isinstance(data, list):
        raise ValueError("掘金热榜缺少 data 列表")
    items: list[NewsItem] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        content = row.get("content") or {}
        if not isinstance(content, dict):
            continue
        external_id = str(content.get("content_id") or "").strip()
        title = str(content.get("title") or "").strip()
        if not external_id or not title:
            continue
        counter = row.get("content_counter") or {}
        if not isinstance(counter, dict):
            counter = {}
        hot = counter.get("hot_rank")
        likes = counter.get("like") or 0
        popularity = float(hot if hot is not None else likes or 0)
        published = None
        try:
            created = int(content.get("ctime") or 0)
        except (TypeError, ValueError):
            created = 0
        if created > 0:
            published = datetime.fromtimestamp(created, timezone.utc)
        author = row.get("author") or {}
        items.append(
            NewsItem(
                source="juejin",
                external_id=external_id,
                title=title,
                url=f"https://juejin.cn/post/{external_id}",
                summary=str(content.get("brief") or "").strip()[:500],
                author=str(author.get("name") or "") if isinstance(author, dict) else "",
                popularity=popularity,
                published_at=published,
                extra={"like": likes or 0, "view": counter.get("view") or 0},
            )
        )
    return items


class JuejinFetcher:
    source_id = "juejin"
    label = "掘金"

    async def run(self, client: httpx.AsyncClient, prefs: Preferences) -> FetchOutcome:
        del prefs
        response = await client.get(RANK_URL)
        response.raise_for_status()
        items = parse_juejin(response.json())
        if not items:
            return FetchOutcome(error="掘金热榜是空的")
        return FetchOutcome(items=items)
