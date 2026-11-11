"""V2EX 热门话题公开 API。"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from app.fetchers.base import FetchOutcome
from app.models import NewsItem, Preferences

HOT_URL = "https://www.v2ex.com/api/topics/hot.json"


def parse_v2ex(data: object) -> list[NewsItem]:
    if isinstance(data, dict):
        message = data.get("message") or "V2EX 返回了非列表数据"
        raise ValueError(str(message))
    if not isinstance(data, list):
        raise ValueError("V2EX 返回了无法识别的数据")
    items: list[NewsItem] = []
    for topic in data:
        if not isinstance(topic, dict):
            continue
        title = str(topic.get("title") or "").strip()
        topic_id = topic.get("id")
        if not title or topic_id is None:
            continue
        external_id = str(topic_id)
        url = str(topic.get("url") or "").strip() or f"https://www.v2ex.com/t/{external_id}"
        content = re.sub(r"\s+", " ", str(topic.get("content") or "")).strip()
        node = topic.get("node") or {}
        node_title = node.get("title") if isinstance(node, dict) else ""
        summary = f"[{node_title}] {content}".strip() if node_title else content
        published = None
        if topic.get("created"):
            try:
                published = datetime.fromtimestamp(int(topic["created"]), timezone.utc)
            except (TypeError, ValueError, OSError):
                published = None
        member = topic.get("member") or {}
        author = member.get("username") if isinstance(member, dict) else ""
        items.append(
            NewsItem(
                source="v2ex",
                external_id=external_id,
                title=title,
                url=url,
                summary=summary[:500],
                author=str(author or ""),
                popularity=float(topic.get("replies") or 0),
                published_at=published,
                extra={"node": node.get("name") if isinstance(node, dict) else ""},
            )
        )
    return items


class V2exFetcher:
    source_id = "v2ex"
    label = "V2EX"

    async def run(self, client: httpx.AsyncClient, prefs: Preferences) -> FetchOutcome:
        del prefs
        response = await client.get(HOT_URL)
        response.raise_for_status()
        items = parse_v2ex(response.json())
        if not items:
            return FetchOutcome(error="V2EX 热门列表是空的")
        return FetchOutcome(items=items)
