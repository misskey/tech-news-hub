"""偏好的默认值、表单解析和宽松的数据库反序列化。"""

from __future__ import annotations

import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models import Keyword, Preferences, RssFeed
from app.sources import CATALOG_IDS, CHANNEL_IDS

DEFAULT_TIMEZONE = "Asia/Shanghai"
MAX_KEYWORDS = 50
MAX_BLOCKED = 50
MAX_LANGUAGES = 6
MAX_FEEDS = 20


def default_preferences() -> Preferences:
    return Preferences(
        keywords=[],
        blocked_keywords=[],
        languages=[],
        enabled_sources=list(CATALOG_IDS),
        items_per_digest=15,
        rss_feeds=[RssFeed(name="InfoQ 中文", url="https://www.infoq.cn/feed", enabled=True)],
        digest_hour=8,
        digest_minute=0,
        timezone=DEFAULT_TIMEZONE,
        channels={channel_id: False for channel_id in CHANNEL_IDS},
        digest_window_hours=36,
        llm_summaries=True,
        llm_model="",
    )


def _format_weight(weight: float) -> str:
    return f"{weight:.2f}".rstrip("0").rstrip(".")


def format_keywords(prefs: Preferences) -> str:
    lines = []
    for keyword in prefs.keywords:
        if keyword.weight == 1:
            lines.append(keyword.text)
        else:
            lines.append(f"{keyword.text}:{_format_weight(keyword.weight)}")
    return "\n".join(lines)


def format_blocked(prefs: Preferences) -> str:
    return "\n".join(prefs.blocked_keywords)


def format_languages(prefs: Preferences) -> str:
    return ", ".join(prefs.languages)


def format_feeds(prefs: Preferences) -> str:
    lines = []
    for feed in prefs.rss_feeds:
        prefix = "" if feed.enabled else "!"
        lines.append(f"{prefix}{feed.name}|{feed.url}")
    return "\n".join(lines)


def _clamp_int(value: object, default: int, low: int, high: int) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _valid_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return DEFAULT_TIMEZONE
    return name


def preferences_from_dict(data: dict | None) -> Preferences:
    """读取数据库里的偏好。字段缺失或类型不对时回退到默认值，避免一次坏数据让服务起不来。"""
    base = default_preferences()
    if not isinstance(data, dict):
        return base
    keywords: list[Keyword] = []
    for raw in data.get("keywords") or []:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        try:
            weight = float(raw.get("weight", 1))
        except (TypeError, ValueError):
            weight = 1.0
        weight = max(-5.0, min(20.0, weight))
        keywords.append(Keyword(text[:80], weight))
    blocked = []
    for raw in data.get("blocked_keywords") or []:
        text = str(raw).strip()
        if text:
            blocked.append(text[:80])
    languages = []
    for raw in data.get("languages") or []:
        text = str(raw).strip()
        if text and text not in languages:
            languages.append(text[:40])
    enabled = [source for source in data.get("enabled_sources") or [] if source in CATALOG_IDS]
    if not enabled:
        enabled = list(base.enabled_sources)
    feeds: list[RssFeed] = []
    if "rss_feeds" in data and isinstance(data.get("rss_feeds"), list):
        for raw in data["rss_feeds"]:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            name = str(raw.get("name") or "").strip() or urlsplit(url).netloc or "RSS"
            feeds.append(RssFeed(name=name[:40], url=url, enabled=bool(raw.get("enabled", True))))
    else:
        feeds = list(base.rss_feeds)
    channels = {channel_id: False for channel_id in CHANNEL_IDS}
    raw_channels = data.get("channels") or {}
    if isinstance(raw_channels, dict):
        for channel_id in CHANNEL_IDS:
            channels[channel_id] = bool(raw_channels.get(channel_id, False))
    return Preferences(
        keywords=keywords[:MAX_KEYWORDS],
        blocked_keywords=blocked[:MAX_BLOCKED],
        languages=languages[:MAX_LANGUAGES],
        enabled_sources=enabled,
        items_per_digest=_clamp_int(data.get("items_per_digest"), 15, 1, 50),
        rss_feeds=feeds[:MAX_FEEDS],
        digest_hour=_clamp_int(data.get("digest_hour"), 8, 0, 23),
        digest_minute=_clamp_int(data.get("digest_minute"), 0, 0, 59),
        timezone=_valid_timezone(str(data.get("timezone") or DEFAULT_TIMEZONE)),
        channels=channels,
        digest_window_hours=_clamp_int(data.get("digest_window_hours"), 36, 6, 168),
        llm_summaries=bool(data.get("llm_summaries", True)),
        llm_model=str(data.get("llm_model") or "").strip()[:80],
    )


def parse_preferences(data: dict) -> tuple[Preferences | None, list[str]]:
    """解析设置表单。返回错误列表时不会给出可保存的偏好。"""
    errors: list[str] = []
    keywords, keyword_errors = _parse_keywords(str(data.get("keywords") or ""))
    errors.extend(keyword_errors)
    blocked, blocked_errors = _parse_blocked(str(data.get("blocked") or ""))
    errors.extend(blocked_errors)
    languages, language_errors = _parse_languages(str(data.get("languages") or ""))
    errors.extend(language_errors)
    feeds, feed_errors = _parse_feeds(str(data.get("rss_feeds") or ""))
    errors.extend(feed_errors)

    sources = [source for source in data.get("sources") or [] if source in CATALOG_IDS]
    if not sources:
        errors.append("至少启用一个来源")

    items_per_digest, count_error = _parse_required_int(
        data.get("items_per_digest"), "每期条数", 1, 50
    )
    if count_error:
        errors.append(count_error)
    hour, hour_error = _parse_required_int(data.get("digest_hour"), "推送小时", 0, 23)
    if hour_error:
        errors.append(hour_error)
    minute, minute_error = _parse_required_int(data.get("digest_minute"), "推送分钟", 0, 59)
    if minute_error:
        errors.append(minute_error)
    window, window_error = _parse_required_int(
        data.get("digest_window_hours"), "早报时间窗口", 6, 168
    )
    if window_error:
        errors.append(window_error)

    timezone = str(data.get("timezone") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        errors.append("时区无效")

    channels = {channel_id: channel_id in (data.get("channels") or []) for channel_id in CHANNEL_IDS}
    llm_summaries = str(data.get("llm_summaries") or "").lower() in {"1", "on", "true", "yes"}
    llm_model = str(data.get("llm_model") or "").strip()[:80]
    if llm_model and not re.fullmatch(r"[A-Za-z0-9_.:/\-]+", llm_model):
        errors.append("模型名称只能包含字母、数字和 . _ - / :")
    if errors:
        return None, errors
    return (
        Preferences(
            keywords=keywords,
            blocked_keywords=blocked,
            languages=languages,
            enabled_sources=sources,
            items_per_digest=items_per_digest or 15,
            rss_feeds=feeds,
            digest_hour=0 if hour is None else hour,
            digest_minute=0 if minute is None else minute,
            timezone=timezone,
            channels=channels,
            digest_window_hours=window or 36,
            llm_summaries=llm_summaries,
            llm_model=llm_model,
        ),
        [],
    )


def _parse_required_int(value: object, label: str, low: int, high: int) -> tuple[int | None, str | None]:
    text = str(value or "").strip()
    if not text:
        return None, f"请填写{label}"
    try:
        number = int(text)
    except ValueError:
        return None, f"{label}需要是整数"
    if number < low or number > high:
        return None, f"{label}需要在 {low} 到 {high} 之间"
    return number, None


def _parse_keywords(text: str) -> tuple[list[Keyword], list[str]]:
    keywords: list[Keyword] = []
    errors: list[str] = []
    seen: set[str] = set()
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.replace("：", ":")
        name = line
        weight = 1.0
        if ":" in line:
            name, weight_text = line.rsplit(":", 1)
            name = name.strip()
            try:
                weight = float(weight_text.strip())
            except ValueError:
                errors.append(f"关键词第 {lineno} 行的权重不是数字")
                continue
        if not name:
            errors.append(f"关键词第 {lineno} 行是空的")
            continue
        if weight < -5 or weight > 20:
            errors.append(f"「{name}」的权重需要在 -5 到 20 之间")
            continue
        key = name.casefold()
        if key in seen:
            keywords = [item for item in keywords if item.text.casefold() != key]
        seen.add(key)
        keywords.append(Keyword(name[:80], weight))
    if len(keywords) > MAX_KEYWORDS:
        errors.append(f"关键词最多 {MAX_KEYWORDS} 个")
    return keywords, errors


def _parse_blocked(text: str) -> tuple[list[str], list[str]]:
    blocked: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        blocked.append(line[:80])
    if len(blocked) > MAX_BLOCKED:
        return blocked[:MAX_BLOCKED], [f"屏蔽词最多 {MAX_BLOCKED} 个"]
    return blocked, []


def _parse_languages(text: str) -> tuple[list[str], list[str]]:
    languages: list[str] = []
    for part in re.split(r"[,，\n]+", text):
        name = part.strip()
        if name and name not in languages:
            languages.append(name[:40])
    if len(languages) > MAX_LANGUAGES:
        return languages[:MAX_LANGUAGES], [f"编程语言最多 {MAX_LANGUAGES} 个"]
    return languages, []


def _parse_feeds(text: str) -> tuple[list[RssFeed], list[str]]:
    feeds: list[RssFeed] = []
    errors: list[str] = []
    seen: set[str] = set()
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        enabled = True
        if line.startswith("!"):
            enabled = False
            line = line[1:].strip()
        if "|" in line:
            name, url = line.split("|", 1)
        else:
            url = line
            name = ""
        url = url.strip()
        name = name.strip()
        if not url.startswith(("http://", "https://")):
            errors.append(f"RSS 第 {lineno} 行的地址需要以 http:// 或 https:// 开头")
            continue
        if not name:
            name = urlsplit(url).netloc or "RSS"
        if url in seen:
            feeds = [feed for feed in feeds if feed.url != url]
        seen.add(url)
        feeds.append(RssFeed(name=name[:40], url=url, enabled=enabled))
    if len(feeds) > MAX_FEEDS:
        errors.append(f"自定义 RSS 最多 {MAX_FEEDS} 个")
    return feeds, errors
