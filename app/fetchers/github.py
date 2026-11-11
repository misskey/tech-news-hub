"""GitHub Trending 每日榜。没有官方 API，解析公开趋势页。"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import quote

import httpx

from app.fetchers.base import FetchOutcome
from app.fetchers.text import clean_text, parse_int
from app.models import NewsItem, Preferences

_ARTICLE = re.compile(r'<article[^>]*class="[^"]*\bBox-row\b[^"]*"[^>]*>', re.I)
_LANG_ALIASES = {
    "golang": "go",
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "csharp": "c#",
    "cpp": "c++",
    "objective c": "objective-c",
}


def github_language_slug(language: str) -> str:
    key = language.strip().casefold()
    slug = _LANG_ALIASES.get(key, language.strip())
    return re.sub(r"\s+", "-", slug)


def trending_url(language: str | None = None) -> str:
    if not language:
        return "https://github.com/trending?since=daily"
    slug = quote(github_language_slug(language), safe="+")
    return f"https://github.com/trending/{slug}?since=daily"


def parse_github_trending(html: str) -> list[NewsItem]:
    parts = _ARTICLE.split(html or "")
    items: list[NewsItem] = []
    seen: set[str] = set()
    for part in parts[1:]:
        end = part.lower().find("</article>")
        article = part if end < 0 else part[:end]
        item = _parse_article(article)
        if item is None or item.external_id in seen:
            continue
        seen.add(item.external_id)
        items.append(item)
    return items


def _parse_article(article: str) -> NewsItem | None:
    heading = re.search(r"<h2[^>]*>(.*?)</h2>", article, re.S | re.I)
    if not heading:
        return None
    href = re.search(r'href="(/[^"]+)"', heading.group(1))
    if not href:
        return None
    path = href.group(1).split("?", 1)[0].strip("/")
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) != 2:
        return None
    owner, repo = segments
    external_id = f"{owner}/{repo}"
    title = clean_text(heading.group(1))
    title = re.sub(r"\s*/\s*", "/", title) or external_id
    description = re.search(r'<p class="[^"]*\bcol-9\b[^"]*">(.*?)</p>', article, re.S | re.I)
    summary = clean_text(description.group(1)) if description else ""
    language_match = re.search(r'itemprop="programmingLanguage"[^>]*>([^<]+)', article)
    language = language_match.group(1).strip() if language_match else ""
    stars_anchor = re.search(r'href="[^"]+/stargazers"[^>]*>(.*?)</a>', article, re.S | re.I)
    forks_anchor = re.search(r'href="[^"]+/forks"[^>]*>(.*?)</a>', article, re.S | re.I)
    stars = parse_int(clean_text(stars_anchor.group(1))) if stars_anchor else 0
    forks = parse_int(clean_text(forks_anchor.group(1))) if forks_anchor else 0
    period = re.search(r"([\d,]+)\s+stars\s+(today|this week|this month)", article, re.I)
    stars_period = parse_int(period.group(1)) if period else 0
    return NewsItem(
        source="github",
        external_id=external_id,
        title=title,
        url=f"https://github.com/{external_id}",
        summary=summary,
        author=owner,
        language=language,
        popularity=float(stars_period or stars),
        extra={"stars": stars, "stars_period": stars_period, "forks": forks},
    )


class GitHubTrendingFetcher:
    source_id = "github"
    label = "GitHub"

    async def run(self, client: httpx.AsyncClient, prefs: Preferences) -> FetchOutcome:
        languages = [language for language in prefs.languages if language.strip()][:6]
        targets = [trending_url(language) for language in languages] or [trending_url()]
        pages = await asyncio.gather(*[_get(client, url) for url in targets], return_exceptions=True)
        items: list[NewsItem] = []
        seen: set[str] = set()
        errors: list[str] = []
        for url, page in zip(targets, pages):
            if isinstance(page, Exception):
                errors.append(f"{url}: {page}")
                continue
            for item in parse_github_trending(page):
                if item.external_id in seen:
                    continue
                seen.add(item.external_id)
                items.append(item)
        if not items:
            detail = "；".join(errors) if errors else "页面里没有解析到仓库，结构可能变了"
            return FetchOutcome(error=detail)
        return FetchOutcome(items=items, error="；".join(errors) or None)


async def _get(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url)
    response.raise_for_status()
    return response.text
