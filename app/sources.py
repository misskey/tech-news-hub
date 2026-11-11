"""内置来源目录。新增来源时在这里登记，设置页会自动出现对应开关。"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import NewsItem


@dataclass(frozen=True)
class SourceInfo:
    id: str
    label: str
    description: str


CATALOG: tuple[SourceInfo, ...] = (
    SourceInfo("github", "GitHub", "每日 Trending，可按编程语言过滤"),
    SourceInfo("hackernews", "Hacker News", "官方 API 的 Top 与 Best 故事"),
    SourceInfo("v2ex", "V2EX", "热门话题"),
    SourceInfo("juejin", "掘金", "综合热门文章"),
    SourceInfo("reddit", "Reddit", "r/programming 热门（Atom）"),
    SourceInfo("sspai", "少数派", "首页最新文章"),
    SourceInfo("producthunt", "Product Hunt", "最新产品发布"),
    SourceInfo("rss", "自定义 RSS", "在下方填写任意 RSS 或 Atom 地址"),
)

CATALOG_IDS = tuple(source.id for source in CATALOG)
CHANNEL_IDS = ("email", "serverchan", "telegram", "wecom", "feishu")

CHANNEL_LABELS = {
    "email": "邮件",
    "serverchan": "Server酱",
    "telegram": "Telegram",
    "wecom": "企业微信",
    "feishu": "飞书",
}


def catalog_label(source_id: str) -> str:
    for source in CATALOG:
        if source.id == source_id:
            return source.label
    return source_id


def source_label(item: NewsItem) -> str:
    if item.source.startswith("rss:"):
        name = (item.extra or {}).get("feed_name")
        if name:
            return str(name)
        return "RSS"
    return catalog_label(item.source)
