"""Read-only client API. Never exposes administration or triggers paid summaries."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException, Query, Request
from app.ranking import rank_items, score_item
from app.sources import source_label
from app.summary import ensure_summaries, assemble_briefing

router = APIRouter(prefix="/api/v1")


def context(request):
    settings = request.app.state.settings
    # Do not turn a protected website into a public API, even if misconfigured.
    if settings.protect_site and not request.session.get("admin"):
        raise HTTPException(401, "本站为私有站点，小程序暂不支持登录")
    db = request.app.state.db
    return db, db.get_preferences(), settings


def present(scored, summaries):
    item = scored.item
    summary = summaries[(item.source, item.external_id)]
    return {"id": item.id, "title": item.title, "source": item.source,
            "source_label": source_label(item), "url": item.url,
            "published_at": item.published_at or item.first_seen_at,
            "short": summary.short, "long": summary.long,
            "takeaways": summary.takeaways, "summary_provider": summary.provider}


@router.get("/news")
def news(request: Request, window: Literal["today", "3d", "7d"] = "today",
         source: str = Query("", max_length=128), q: str = Query("", max_length=100),
         page: int = Query(1, ge=1, le=1000), page_size: int = Query(20, ge=1, le=50)):
    db, prefs, settings = context(request)
    now = datetime.now(ZoneInfo(prefs.timezone))
    since = now.replace(hour=0, minute=0, second=0, microsecond=0) if window == "today" else now - timedelta(days=int(window[0]))
    # Same bounded candidate pool as the web homepage; disclose the bound.
    candidates = db.items_since(since.astimezone(timezone.utc))
    ranked = rank_items(candidates, prefs)
    sources = {s.item.source: source_label(s.item) for s in ranked}
    filtered = [s for s in ranked if (not source or s.item.source == source) and
                (not q.strip() or q.strip().casefold() in f"{s.item.title}\n{s.item.summary}".casefold())]
    start = (page - 1) * page_size
    visible = filtered[start:start + page_size]
    summaries = ensure_summaries(db, [s.item for s in ranked[:12] + visible], prefs, settings, allow_llm=False)
    briefing = asdict(assemble_briefing(ranked[:12], summaries))
    if window != "today":
        briefing["overview"] = briefing["overview"].replace("今天", "所选时段")
    return {"items": [present(s, summaries) for s in visible], "total": len(filtered),
            "page": page, "has_more": start + page_size < len(filtered),
            "sources": [{"id": key, "label": label} for key, label in sources.items()],
            "briefing": briefing,
            "date": now.strftime("%Y-%m-%d"), "candidate_limit": 500,
            "candidate_limit_reached": len(candidates) == 500}


@router.get("/news/{item_id}")
def detail(request: Request, item_id: int):
    db, prefs, settings = context(request)
    item = db.get_item(item_id)
    if item is None or not rank_items([item], prefs):
        raise HTTPException(404, "资讯不存在或已不可见")
    summaries = ensure_summaries(db, [item], prefs, settings, allow_llm=False)
    return present(score_item(item, prefs), summaries)
