"""来源注册表。新增抓取器时在 build_fetchers 里挂上，并在 sources.CATALOG 登记。"""

from __future__ import annotations

from app.config import Settings
from app.fetchers.base import Fetcher
from app.fetchers.github import GitHubTrendingFetcher
from app.fetchers.hackernews import HackerNewsFetcher
from app.fetchers.juejin import JuejinFetcher
from app.fetchers.producthunt import ProductHuntFetcher
from app.fetchers.reddit import RedditFetcher
from app.fetchers.rss import RssFetcher
from app.fetchers.sspai import SspaiFetcher
from app.fetchers.v2ex import V2exFetcher
from app.models import Preferences


def build_fetchers(prefs: Preferences, settings: Settings) -> list[Fetcher]:
    enabled = set(prefs.enabled_sources)
    fetchers: list[Fetcher] = []
    if "github" in enabled:
        fetchers.append(GitHubTrendingFetcher())
    if "hackernews" in enabled:
        fetchers.append(HackerNewsFetcher(limit=settings.hn_story_limit))
    if "v2ex" in enabled:
        fetchers.append(V2exFetcher())
    if "juejin" in enabled:
        fetchers.append(JuejinFetcher())
    if "reddit" in enabled:
        fetchers.append(RedditFetcher())
    if "sspai" in enabled:
        fetchers.append(SspaiFetcher())
    if "producthunt" in enabled:
        fetchers.append(ProductHuntFetcher())
    if "rss" in enabled:
        feeds = [feed for feed in prefs.rss_feeds if feed.enabled and feed.url]
        if feeds:
            fetchers.append(RssFetcher(feeds))
    return fetchers
