"""抓取器的公共类型。解析函数保持纯函数，方便用录制的响应做测试。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.models import NewsItem, Preferences

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class FetchOutcome:
    items: list[NewsItem] = field(default_factory=list)
    error: str | None = None


class Fetcher(Protocol):
    source_id: str
    label: str

    async def run(self, client: httpx.AsyncClient, prefs: Preferences) -> FetchOutcome: ...
