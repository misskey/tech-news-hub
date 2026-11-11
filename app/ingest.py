"""并发抓取。单个来源抛错只记日志，不中断整次运行。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from app.fetchers.base import USER_AGENT, Fetcher
from app.models import NewsItem, Preferences

logger = logging.getLogger(__name__)


@dataclass
class SourceReport:
    source_id: str
    label: str
    ok: bool
    count: int
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "label": self.label,
            "ok": self.ok,
            "count": self.count,
            "error": self.error,
        }


def make_client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


async def collect(
    fetchers: list[Fetcher],
    client: httpx.AsyncClient,
    prefs: Preferences,
    *,
    source_timeout: float = 90,
) -> tuple[list[NewsItem], list[SourceReport]]:
    async def one(fetcher: Fetcher) -> tuple[list[NewsItem], SourceReport]:
        try:
            outcome = await asyncio.wait_for(fetcher.run(client, prefs), timeout=source_timeout)
        except Exception as exc:
            logger.exception("来源 %s 抓取失败", fetcher.source_id)
            return [], SourceReport(fetcher.source_id, fetcher.label, False, 0, _short(exc))
        if outcome.error and not outcome.items:
            logger.error("来源 %s 抓取失败：%s", fetcher.source_id, outcome.error)
            return [], SourceReport(fetcher.source_id, fetcher.label, False, 0, outcome.error)
        if outcome.error:
            logger.warning("来源 %s 部分失败：%s", fetcher.source_id, outcome.error)
            return outcome.items, SourceReport(
                fetcher.source_id, fetcher.label, False, len(outcome.items), outcome.error
            )
        logger.info("来源 %s 获得 %s 条", fetcher.source_id, len(outcome.items))
        return outcome.items, SourceReport(fetcher.source_id, fetcher.label, True, len(outcome.items))

    pairs = await asyncio.gather(*[one(fetcher) for fetcher in fetchers])
    items: list[NewsItem] = []
    reports: list[SourceReport] = []
    for batch, report in pairs:
        items.extend(batch)
        reports.append(report)
    return items, reports


def _short(exc: Exception) -> str:
    text = f"{exc.__class__.__name__}: {exc}"
    return text[:300]
