"""抓取结果和用户偏好的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Keyword:
    text: str
    weight: float = 1.0


@dataclass
class RssFeed:
    name: str
    url: str
    enabled: bool = True


@dataclass
class Preferences:
    keywords: list[Keyword] = field(default_factory=list)
    blocked_keywords: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    enabled_sources: list[str] = field(default_factory=list)
    items_per_digest: int = 15
    rss_feeds: list[RssFeed] = field(default_factory=list)
    digest_hour: int = 8
    digest_minute: int = 0
    timezone: str = "Asia/Shanghai"
    channels: dict[str, bool] = field(default_factory=dict)
    digest_window_hours: int = 36

    def to_dict(self) -> dict:
        return {
            "keywords": [{"text": item.text, "weight": item.weight} for item in self.keywords],
            "blocked_keywords": list(self.blocked_keywords),
            "languages": list(self.languages),
            "enabled_sources": list(self.enabled_sources),
            "items_per_digest": self.items_per_digest,
            "rss_feeds": [
                {"name": feed.name, "url": feed.url, "enabled": feed.enabled} for feed in self.rss_feeds
            ],
            "digest_hour": self.digest_hour,
            "digest_minute": self.digest_minute,
            "timezone": self.timezone,
            "channels": dict(self.channels),
            "digest_window_hours": self.digest_window_hours,
        }


@dataclass
class NewsItem:
    source: str
    external_id: str
    title: str
    url: str
    summary: str = ""
    author: str = ""
    language: str = ""
    popularity: float = 0
    published_at: datetime | None = None
    extra: dict = field(default_factory=dict)
    id: int | None = None
    first_seen_at: datetime | None = None
    fetched_at: datetime | None = None


@dataclass
class ScoredItem:
    item: NewsItem
    score: float
    keyword_score: float
    language_score: float
    popularity_score: float
    matched: list[str]
