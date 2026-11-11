"""抓取入库和生成推送。Web、定时任务和命令行都走这里。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.db import Database
from app.digest import Digest, build_digest
from app.fetchers import build_fetchers
from app.ingest import SourceReport, collect, make_client
from app.notifiers import CHANNELS

logger = logging.getLogger(__name__)


@dataclass
class FetchReport:
    inserted: int
    updated: int
    sources: list[SourceReport] = field(default_factory=list)

    @property
    def any_success(self) -> bool:
        return any(source.count > 0 for source in self.sources)

    def to_dict(self) -> dict:
        return {
            "inserted": self.inserted,
            "updated": self.updated,
            "sources": [source.to_dict() for source in self.sources],
        }

    def summary(self) -> str:
        if not self.sources:
            return "没有启用的来源"
        text = f"抓取完成：新增 {self.inserted}，更新 {self.updated}"
        failed = [source.label for source in self.sources if not source.ok]
        if failed:
            text += "。已跳过失败来源：" + "、".join(failed)
        return text


@dataclass
class ChannelResult:
    channel_id: str
    label: str
    ok: bool
    message: str
    attempted: bool

    def to_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "label": self.label,
            "ok": self.ok,
            "message": self.message,
            "attempted": self.attempted,
        }


@dataclass
class PushReport:
    title: str
    count: int
    results: list[ChannelResult] = field(default_factory=list)
    note: str = ""

    @property
    def attempted_failures(self) -> list[ChannelResult]:
        return [result for result in self.results if result.attempted and not result.ok]

    @property
    def attempted_successes(self) -> list[ChannelResult]:
        return [result for result in self.results if result.attempted and result.ok]

    def summary(self) -> str:
        if self.note and not self.results:
            return self.note
        if not self.results:
            return self.note or "没有推送"
        sent = [result.label for result in self.attempted_successes]
        failed = [result.label for result in self.attempted_failures]
        skipped = [result.label for result in self.results if not result.attempted]
        parts = [f"《{self.title}》共 {self.count} 条"]
        if sent:
            parts.append("已发送到" + "、".join(sent))
        if failed:
            parts.append("发送失败：" + "、".join(failed))
        if skipped:
            parts.append("未配置已跳过：" + "、".join(skipped))
        if self.note:
            parts.append(self.note)
        return "。".join(parts)


async def fetch_and_store(db: Database, settings: Settings) -> FetchReport:
    started = datetime.now(timezone.utc)
    prefs = db.get_preferences()
    fetchers = build_fetchers(prefs, settings)
    if not fetchers:
        report = FetchReport(0, 0, [])
        db.add_fetch_run(started, report.to_dict())
        return report
    async with make_client(settings.fetch_timeout) as client:
        items, sources = await collect(fetchers, client, prefs)
    inserted, updated = db.upsert_items(items)
    report = FetchReport(inserted, updated, sources)
    db.add_fetch_run(started, report.to_dict())
    logger.info(report.summary())
    return report


async def push_digest(db: Database, settings: Settings, *, now: datetime | None = None) -> PushReport:
    prefs = db.get_preferences()
    moment = now or datetime.now(timezone.utc)
    since = moment - timedelta(hours=prefs.digest_window_hours)
    items = db.items_since(since)
    digest: Digest = build_digest(items, prefs, now=moment)
    if not digest.entries:
        report = PushReport(digest.title, 0, note="最近没有可推送的新内容，先抓取一次")
        _remember_push(db, report)
        return report
    results: list[ChannelResult] = []
    enabled = False
    for channel in CHANNELS:
        if not prefs.channels.get(channel.id):
            continue
        enabled = True
        if not channel.configured(settings):
            results.append(ChannelResult(channel.id, channel.label, False, "已勾选，但环境变量还没配好", False))
            continue
        try:
            await channel.send(digest, settings)
        except Exception as exc:
            logger.exception("推送渠道 %s 失败", channel.id)
            results.append(ChannelResult(channel.id, channel.label, False, str(exc)[:300], True))
        else:
            results.append(ChannelResult(channel.id, channel.label, True, "已发送", True))
    note = "" if enabled else "没有勾选推送渠道。在设置页勾选并保存后才会发送。"
    report = PushReport(digest.title, len(digest.entries), results, note)
    _remember_push(db, report)
    logger.info(report.summary())
    return report


def _remember_push(db: Database, report: PushReport) -> None:
    db.set_last_push(
        {
            "title": report.title,
            "count": report.count,
            "note": report.note,
            "summary": report.summary(),
            "results": [result.to_dict() for result in report.results],
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
