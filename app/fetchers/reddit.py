"""Reddit r/programming。JSON 接口经常被拦，改用公开 Atom，并把外链从正文里提出来。"""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urlsplit

import httpx

from app.fetchers.base import FetchOutcome
from app.fetchers.rss import parse_feed, parse_xml
from app.models import NewsItem, Preferences

FEED_URL = "https://www.reddit.com/r/programming/.rss"


def parse_reddit_atom(xml_text: str) -> list[NewsItem]:
    items = parse_feed(xml_text, source="reddit", feed_name="r/programming", feed_url=FEED_URL)
    contents = _content_by_id(xml_text)
    for item in items:
        content = contents.get(item.external_id, "")
        item.url = _external_url(content, item.url)
        if "submitted by" in item.summary.casefold():
            item.summary = ""
    return items


class RedditFetcher:
    source_id = "reddit"
    label = "Reddit"

    async def run(self, client: httpx.AsyncClient, prefs: Preferences) -> FetchOutcome:
        del prefs
        response = await client.get(FEED_URL)
        response.raise_for_status()
        items = parse_reddit_atom(response.text)
        if not items:
            return FetchOutcome(error="Reddit Atom 没有解析到帖子")
        return FetchOutcome(items=items)


def _content_by_id(xml_text: str) -> dict[str, str]:
    try:
        root = parse_xml(xml_text)
    except Exception:
        return {}
    found: dict[str, str] = {}
    for element in root.iter():
        if _local(element.tag) != "entry":
            continue
        entry_id = ""
        content = ""
        for child in list(element):
            name = _local(child.tag)
            if name == "id":
                entry_id = "".join(child.itertext()).strip()
            elif name == "content":
                content = "".join(child.itertext())
        if entry_id:
            found[entry_id] = content
    return found


def _external_url(content: str, fallback: str) -> str:
    decoded = unescape(content or "")
    for href in re.findall(r'href="(https?://[^"]+)"', decoded):
        host = urlsplit(href).netloc.lower()
        if "reddit.com" in host or host.endswith("redd.it"):
            continue
        return href
    return fallback


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if tag else ""
