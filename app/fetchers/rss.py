"""RSS 2.0 与 Atom 的通用解析，也供 Reddit 和 Product Hunt 复用。"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.fetchers.base import FetchOutcome
from app.fetchers.text import clean_text
from app.models import NewsItem, Preferences, RssFeed


def feed_source_id(url: str) -> str:
    digest = hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:10]
    return f"rss:{digest}"


def parse_xml(text: str) -> ET.Element:
    cleaned = (text or "").lstrip("\ufeff")
    cleaned = re.sub(
        r"(<\?xml[^>]*?)encoding=[\"'][^\"']+[\"']",
        r"\1encoding='utf-8'",
        cleaned,
        count=1,
    )
    return ET.fromstring(cleaned)


def parse_feed(xml_text: str, *, source: str, feed_name: str, feed_url: str = "") -> list[NewsItem]:
    root = parse_xml(xml_text)
    entries = [element for element in root.iter() if _local(element.tag) in {"item", "entry"}]
    items: list[NewsItem] = []
    total = len(entries)
    for index, entry in enumerate(entries):
        title = clean_text(_child_text(entry, "title"))
        url = _entry_url(entry)
        if not title or not url.startswith(("http://", "https://")):
            continue
        external_id = (_child_text(entry, "guid") or _child_text(entry, "id") or url).strip()[:300]
        summary = _summary(entry)
        if summary == title or re.fullmatch(r"点击查看原文[>》]?", summary or ""):
            summary = ""
        published = _published(entry)
        items.append(
            NewsItem(
                source=source,
                external_id=external_id,
                title=title[:300],
                url=url,
                summary=summary[:500],
                author=_author(entry)[:80],
                popularity=float(max(total - index, 1)),
                published_at=published,
                extra={"feed_name": feed_name, "feed_url": feed_url},
            )
        )
    return items


class RssFetcher:
    source_id = "rss"
    label = "自定义 RSS"

    def __init__(self, feeds: list[RssFeed]):
        self.feeds = feeds

    async def run(self, client: httpx.AsyncClient, prefs: Preferences) -> FetchOutcome:
        del prefs
        items: list[NewsItem] = []
        errors: list[str] = []
        for feed in self.feeds:
            if not feed.enabled:
                continue
            try:
                response = await client.get(feed.url)
                response.raise_for_status()
                parsed = parse_feed(
                    response.text,
                    source=feed_source_id(feed.url),
                    feed_name=feed.name,
                    feed_url=feed.url,
                )
                if not parsed:
                    errors.append(f"{feed.name}: 没有解析到条目")
                    continue
                items.extend(parsed)
            except Exception as exc:  # 单个订阅失败不影响其他订阅
                errors.append(f"{feed.name}: {exc}")
        error = "；".join(errors) if errors else None
        if not items:
            return FetchOutcome(error=error or "没有可用的 RSS")
        return FetchOutcome(items=items, error=error)


def _local(tag: str) -> str:
    if not tag:
        return ""
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str:
    for child in list(element):
        if _local(child.tag) == name:
            return "".join(child.itertext()).strip()
    return ""


def _entry_url(element: ET.Element) -> str:
    alternate = ""
    first_href = ""
    rss_text = ""
    for child in list(element):
        if _local(child.tag) != "link":
            continue
        href = (child.get("href") or "").strip()
        text = "".join(child.itertext()).strip()
        rel = (child.get("rel") or "").strip()
        if href:
            if not first_href:
                first_href = href
            if rel in {"", "alternate"} and not alternate:
                alternate = href
            if rel == "alternate":
                alternate = href
        elif text.startswith(("http://", "https://")):
            rss_text = text
    return rss_text or alternate or first_href


def _summary(element: ET.Element) -> str:
    for name in ("description", "summary", "content"):
        for child in list(element):
            if _local(child.tag) != name:
                continue
            text = clean_text("".join(child.itertext()))
            if text:
                return text
    return ""


def _author(element: ET.Element) -> str:
    for child in list(element):
        if _local(child.tag) == "author":
            name = _child_text(child, "name")
            if name:
                return clean_text(name)
            text = clean_text("".join(child.itertext()))
            if text:
                return text
        if _local(child.tag) == "creator":
            text = clean_text("".join(child.itertext()))
            if text:
                return text
    return ""


def _published(element: ET.Element) -> datetime | None:
    for name in ("published", "pubDate", "updated", "date"):
        text = _child_text(element, name)
        if not text:
            continue
        parsed = _parse_date(text)
        if parsed is not None:
            return parsed
    return None


def _parse_date(text: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    candidate = text.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
