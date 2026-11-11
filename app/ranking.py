"""把偏好和来源热度合成一个可排序的分数。

分数 = 命中关键词的权重之和 × 100 + 语言加分 + ln(1 + 热度)。

权重 1 的关键词是 100 分。真实世界里热度的对数通常只有 0 到 12 分，
所以只要命中了兴趣，就会排在纯热门内容前面。两个条目命中同一组关键词时，
热度决定先后。未配置任何关键词时，排序基本只看热度（以及语言加分）。

英文关键词按词边界匹配，避免「AI」命中「email」。中文关键词按子串匹配。
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.models import NewsItem, Preferences, ScoredItem

KEYWORD_FACTOR = 100.0
LANGUAGE_BONUS = 3.0

_LANG_ALIASES = {
    "golang": "go",
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "csharp": "c#",
    "cpp": "c++",
    "rs": "rust",
    "objective c": "objective-c",
}

_CJK = re.compile(r"[\u3400-\u9fff]")
_DROP_QUERY = {"ref", "source", "spm", "from"}


def canonical_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return url.strip()
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    kept = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in _DROP_QUERY:
            continue
        kept.append((key, value))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(kept), ""))


def keyword_in(text: str, keyword: str) -> bool:
    needle = keyword.casefold().strip()
    if not needle:
        return False
    haystack = text.casefold()
    if _CJK.search(needle):
        return needle in haystack
    pattern = re.compile(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])")
    return pattern.search(haystack) is not None


def _norm_lang(value: str) -> str:
    key = value.strip().casefold()
    return _LANG_ALIASES.get(key, key)


def _source_enabled(item: NewsItem, prefs: Preferences) -> bool:
    enabled = set(prefs.enabled_sources)
    if item.source.startswith("rss:"):
        if "rss" not in enabled:
            return False
        feed_url = str((item.extra or {}).get("feed_url") or "")
        if not feed_url:
            return True
        for feed in prefs.rss_feeds:
            if feed.url == feed_url:
                return feed.enabled
        return True
    return item.source in enabled


def _is_blocked(text: str, prefs: Preferences) -> bool:
    return any(keyword_in(text, blocked) for blocked in prefs.blocked_keywords)


def score_item(item: NewsItem, prefs: Preferences) -> ScoredItem | None:
    if not _source_enabled(item, prefs):
        return None
    blob = f"{item.title}\n{item.summary}"
    if _is_blocked(blob, prefs):
        return None
    matched: list[str] = []
    weight_sum = 0.0
    for keyword in prefs.keywords:
        if keyword_in(blob, keyword.text):
            matched.append(keyword.text)
            weight_sum += keyword.weight
    language_score = 0.0
    if prefs.languages and item.language:
        wanted = {_norm_lang(language) for language in prefs.languages}
        if _norm_lang(item.language) in wanted:
            language_score = LANGUAGE_BONUS
    popularity_score = math.log1p(max(float(item.popularity or 0), 0.0))
    keyword_score = weight_sum * KEYWORD_FACTOR
    return ScoredItem(
        item=item,
        score=keyword_score + language_score + popularity_score,
        keyword_score=keyword_score,
        language_score=language_score,
        popularity_score=popularity_score,
        matched=matched,
    )


def rank_items(
    items: list[NewsItem],
    prefs: Preferences,
    *,
    limit: int | None = None,
) -> list[ScoredItem]:
    scored = []
    for item in items:
        result = score_item(item, prefs)
        if result is not None:
            scored.append(result)
    scored.sort(key=_sort_key, reverse=True)
    scored = _dedupe(scored)
    if limit is not None:
        return scored[: max(0, limit)]
    return scored


def _sort_key(scored: ScoredItem) -> tuple:
    published = scored.item.published_at or scored.item.first_seen_at
    timestamp = published.timestamp() if isinstance(published, datetime) else 0
    return (scored.score, timestamp, scored.item.popularity, scored.item.external_id)


def _dedupe(scored: list[ScoredItem]) -> list[ScoredItem]:
    seen: set[str] = set()
    unique: list[ScoredItem] = []
    for item in scored:
        key = canonical_url(item.item.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
