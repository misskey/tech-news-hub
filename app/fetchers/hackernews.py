"""Hacker News 官方 Firebase API：Top 与 Best。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from app.fetchers.base import FetchOutcome
from app.fetchers.text import clean_text
from app.models import NewsItem, Preferences

API = "https://hacker-news.firebaseio.com/v0"


def parse_hn_items(items: list[dict]) -> list[NewsItem]:
    results: list[NewsItem] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in (None, "story"):
            continue
        if item.get("deleted") or item.get("dead"):
            continue
        title = str(item.get("title") or "").strip()
        external_id = str(item.get("id") or "").strip()
        if not title or not external_id or external_id in seen:
            continue
        seen.add(external_id)
        url = str(item.get("url") or "").strip() or f"https://news.ycombinator.com/item?id={external_id}"
        published = None
        if item.get("time"):
            try:
                published = datetime.fromtimestamp(int(item["time"]), timezone.utc)
            except (TypeError, ValueError, OSError):
                published = None
        results.append(
            NewsItem(
                source="hackernews",
                external_id=external_id,
                title=title,
                url=url,
                summary=clean_text(str(item.get("text") or ""))[:500],
                author=str(item.get("by") or ""),
                popularity=float(item.get("score") or 0),
                published_at=published,
                extra={
                    "comments": item.get("descendants") or 0,
                    "hn_url": f"https://news.ycombinator.com/item?id={external_id}",
                },
            )
        )
    return results


class HackerNewsFetcher:
    source_id = "hackernews"
    label = "Hacker News"

    def __init__(self, limit: int = 30):
        self.limit = limit

    async def run(self, client: httpx.AsyncClient, prefs: Preferences) -> FetchOutcome:
        del prefs
        top = await _ids(client, "topstories")
        best = await _ids(client, "beststories")
        ordered: list[int] = []
        seen: set[int] = set()
        for story_id in list(top[: self.limit]) + list(best[: max(10, self.limit // 2)]):
            if story_id in seen:
                continue
            seen.add(story_id)
            ordered.append(story_id)
        semaphore = asyncio.Semaphore(8)

        async def one(story_id: int) -> dict:
            async with semaphore:
                response = await client.get(f"{API}/item/{story_id}.json")
                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, dict) else {}

        raws = await asyncio.gather(*[one(story_id) for story_id in ordered], return_exceptions=True)
        stories = [raw for raw in raws if isinstance(raw, dict)]
        failures = sum(1 for raw in raws if isinstance(raw, Exception))
        items = parse_hn_items(stories)
        if not items:
            return FetchOutcome(error="Hacker News 没有返回可用的故事")
        error = f"{failures} 条故事拉取失败" if failures else None
        return FetchOutcome(items=items, error=error)


async def _ids(client: httpx.AsyncClient, kind: str) -> list[int]:
    response = await client.get(f"{API}/{kind}.json")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"{kind} 返回的不是列表")
    ids: list[int] = []
    for value in payload:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids
