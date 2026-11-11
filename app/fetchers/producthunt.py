"""Product Hunt 公开 Atom。"""

from __future__ import annotations

import re

import httpx

from app.fetchers.base import FetchOutcome
from app.fetchers.rss import parse_feed
from app.models import Preferences

FEED_URL = "https://www.producthunt.com/feed"


def parse_producthunt(xml_text: str):
    items = parse_feed(xml_text, source="producthunt", feed_name="Product Hunt", feed_url=FEED_URL)
    for item in items:
        item.summary = re.sub(r"\s*Discussion\s*\|\s*Link\s*$", "", item.summary).strip()
    return items


class ProductHuntFetcher:
    source_id = "producthunt"
    label = "Product Hunt"

    async def run(self, client: httpx.AsyncClient, prefs: Preferences) -> FetchOutcome:
        del prefs
        response = await client.get(FEED_URL)
        response.raise_for_status()
        items = parse_producthunt(response.text)
        if not items:
            return FetchOutcome(error="Product Hunt 没有解析到产品")
        return FetchOutcome(items=items)
