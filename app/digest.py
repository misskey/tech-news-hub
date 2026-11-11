"""把排好序的条目渲染成早报。各推送渠道共用这里的正文。"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.models import NewsItem, Preferences
from app.ranking import rank_items
from app.sources import source_label


@dataclass
class DigestEntry:
    title: str
    url: str
    source_label: str
    score: float
    summary: str
    matched: list[str]
    popularity: float
    language: str


@dataclass
class Digest:
    title: str
    generated_at: datetime
    entries: list[DigestEntry] = field(default_factory=list)
    window_hours: int = 36


def build_digest(
    items: list[NewsItem],
    prefs: Preferences,
    *,
    now: datetime | None = None,
) -> Digest:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(ZoneInfo(prefs.timezone))
    ranked = rank_items(items, prefs, limit=prefs.items_per_digest)
    entries = [
        DigestEntry(
            title=item.item.title,
            url=item.item.url,
            source_label=source_label(item.item),
            score=item.score,
            summary=_brief(item.item.summary),
            matched=list(item.matched),
            popularity=item.item.popularity,
            language=item.item.language,
        )
        for item in ranked
    ]
    return Digest(
        title=f"科技早报 {local.strftime('%Y-%m-%d')}",
        generated_at=moment,
        entries=entries,
        window_hours=prefs.digest_window_hours,
    )


def render_markdown(digest: Digest) -> str:
    lines = [f"## {digest.title}", ""]
    if not digest.entries:
        lines.append("这个时间窗口里没有可推送的内容。")
        lines.append("")
    for index, entry in enumerate(digest.entries, 1):
        lines.append(f"{index}. [{entry.title}]({entry.url})")
        lines.append("   " + " · ".join(_meta(entry)))
        if entry.summary:
            lines.append(f"   {entry.summary}")
        lines.append("")
    lines.append(f"共 {len(digest.entries)} 条 · 由 tech-news-hub 生成")
    return "\n".join(lines).strip()


def render_plain(digest: Digest) -> str:
    lines = [digest.title, ""]
    if not digest.entries:
        lines.append("这个时间窗口里没有可推送的内容。")
    for index, entry in enumerate(digest.entries, 1):
        lines.append(f"{index}. {entry.title}")
        lines.append(f"   {entry.url}")
        lines.append("   " + " · ".join(_meta(entry)))
        if entry.summary:
            lines.append(f"   {entry.summary}")
        lines.append("")
    lines.append(f"共 {len(digest.entries)} 条 · 由 tech-news-hub 生成")
    return "\n".join(lines).strip()


def render_html(digest: Digest) -> str:
    rows = [
        "<!DOCTYPE html><html><body style=\"font-family:sans-serif;color:#1c1915\">",
        f"<h2>{html.escape(digest.title)}</h2>",
        "<ol>",
    ]
    for entry in digest.entries:
        rows.append("<li style=\"margin:0 0 12px\">")
        rows.append(
            f'<a href="{html.escape(entry.url, quote=True)}">{html.escape(entry.title)}</a>'
        )
        rows.append(f"<div style=\"color:#5c564e;font-size:13px\">{html.escape(' · '.join(_meta(entry)))}</div>")
        if entry.summary:
            rows.append(f"<div>{html.escape(entry.summary)}</div>")
        rows.append("</li>")
    if not digest.entries:
        rows.append("<li>这个时间窗口里没有可推送的内容。</li>")
    rows.append("</ol>")
    rows.append(f"<p style=\"color:#5c564e\">共 {len(digest.entries)} 条 · 由 tech-news-hub 生成</p>")
    rows.append("</body></html>")
    return "".join(rows)


def telegram_messages(digest: Digest) -> list[str]:
    header = f"<b>{html.escape(digest.title)}</b>"
    if not digest.entries:
        return [header + "\n\n这个时间窗口里没有可推送的内容。"]
    messages: list[str] = []
    current = header + "\n"
    for index, entry in enumerate(digest.entries, 1):
        block = (
            f'{index}. <a href="{html.escape(entry.url, quote=True)}">{html.escape(entry.title)}</a>\n'
            f"{html.escape(' · '.join(_meta(entry)))}"
        )
        if entry.summary:
            block += "\n" + html.escape(entry.summary)
        block += "\n"
        if len(current) + len(block) > 3500:
            messages.append(current.strip())
            current = header + "（续）\n" + block
        else:
            current += block
    if current.strip():
        messages.append(current.strip())
    return messages


def _meta(entry: DigestEntry) -> list[str]:
    parts = [entry.source_label, f"得分 {entry.score:.1f}"]
    if entry.matched:
        parts.append("、".join(entry.matched))
    return parts


def _brief(text: str, limit: int = 100) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "…"
