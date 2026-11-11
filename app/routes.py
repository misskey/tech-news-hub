"""页面路由。浏览页默认可公开，设置页在配置了管理密码后需要登录。"""

from __future__ import annotations

import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.templating import Jinja2Templates

from app.db import from_iso
from app.models import Preferences
from app.notifiers import CHANNELS
from app.pipeline import fetch_and_store, push_digest
from app.prefs import (
    format_blocked,
    format_feeds,
    format_keywords,
    format_languages,
    parse_preferences,
)
from app.ranking import keyword_in, rank_items, score_item
from app.scheduler import reschedule
from app.sources import CATALOG, source_label
from app.summary import ensure_briefing, ensure_summaries

logger = logging.getLogger(__name__)

TIMEZONES = (
    "Asia/Shanghai",
    "Asia/Hong_Kong",
    "Asia/Taipei",
    "Asia/Tokyo",
    "Asia/Singapore",
    "UTC",
    "Europe/London",
    "America/Los_Angeles",
    "America/New_York",
)
CHANNEL_HINTS = {
    "email": "需要 SMTP_HOST、SMTP_TO，登录账号用 SMTP_USER / SMTP_PASSWORD",
    "serverchan": "需要 SERVERCHAN_SENDKEY",
    "telegram": "需要 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID",
    "wecom": "需要 WECOM_WEBHOOK",
    "feishu": "需要 FEISHU_WEBHOOK，如果机器人开了签名再填 FEISHU_SECRET",
}
WINDOWS = (
    ("today", "今天"),
    ("3d", "近 3 天"),
    ("7d", "近 7 天"),
)


def register(app: FastAPI, templates: Jinja2Templates) -> None:
    @app.get("/")
    def home(request: Request):
        settings = request.app.state.settings
        denied = _guard_site(request, settings)
        if denied is not None:
            return denied
        db = request.app.state.db
        prefs = db.get_preferences()
        zone = ZoneInfo(prefs.timezone)
        window = request.query_params.get("window") or "today"
        if window not in {item[0] for item in WINDOWS}:
            window = "today"
        source = (request.query_params.get("source") or "").strip()
        topic = (request.query_params.get("topic") or "").strip()
        query = (request.query_params.get("q") or "").strip()
        now_local = datetime.now(zone)
        if window == "7d":
            since = now_local - timedelta(days=7)
        elif window == "3d":
            since = now_local - timedelta(days=3)
        else:
            since = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        day_scored = rank_items(db.items_since(since.astimezone(timezone.utc)), prefs)
        source_options = []
        seen = set()
        for item in day_scored:
            if item.item.source in seen:
                continue
            seen.add(item.item.source)
            source_options.append({"id": item.item.source, "label": source_label(item.item)})
        scored = day_scored
        if source:
            scored = [item for item in scored if item.item.source == source]
        if topic:
            scored = [
                item
                for item in scored
                if topic in item.matched or keyword_in(f"{item.item.title}\n{item.item.summary}", topic)
            ]
        if query:
            needle = query.casefold()
            scored = [
                item
                for item in scored
                if needle in f"{item.item.title}\n{item.item.summary}".casefold()
            ]
        truncated = len(scored) > 200
        visible = scored[:200]
        summaries = ensure_summaries(
            db,
            [item.item for item in day_scored[:12] + visible],
            prefs,
            settings,
            allow_llm=False,
        )
        briefing = None
        if day_scored:
            briefing = ensure_briefing(
                db,
                day_scored,
                summaries,
                prefs,
                settings,
                now=datetime.now(timezone.utc),
                allow_llm=False,
            )
        rows = [_row(item, zone, summaries.get((item.item.source, item.item.external_id))) for item in visible]

        def href(**updates: str) -> str:
            params = {"window": window, "source": source, "topic": topic, "q": query}
            params.update(updates)
            kept = {key: value for key, value in params.items() if value}
            encoded = urlencode(kept)
            return f"/?{encoded}" if encoded else "/"

        weekday = "一二三四五六日"[now_local.weekday()]
        fetch_run = _present_fetch_run(db.latest_fetch_run(), zone)
        return _render(
            templates,
            request,
            "index.html",
            {
                "rows": rows,
                "truncated": truncated,
                "date_label": now_local.strftime(f"%Y年%m月%d日 周{weekday}"),
                "window": window,
                "windows": [
                    {"id": key, "label": label, "href": href(window=key), "on": window == key}
                    for key, label in WINDOWS
                ],
                "source": source,
                "source_options": source_options,
                "topic": topic,
                "query": query,
                "keywords": prefs.keywords,
                "topic_links": [
                    {
                        "text": keyword.text,
                        "href": href(topic="" if topic == keyword.text else keyword.text),
                        "on": topic == keyword.text,
                    }
                    for keyword in prefs.keywords
                ],
                "clear_href": href(source="", topic="", q=""),
                "has_any": db.count_items() > 0,
                "fetch_run": fetch_run,
                "password_set": bool(settings.admin_password),
                "briefing": briefing,
            },
        )

    @app.get("/items/{item_id}")
    def item_page(request: Request, item_id: int):
        settings = request.app.state.settings
        denied = _guard_site(request, settings)
        if denied is not None:
            return denied
        db = request.app.state.db
        item = db.get_item(item_id)
        if item is None:
            return _render(templates, request, "item.html", {"missing": True}, status_code=404)
        prefs = db.get_preferences()
        summaries = ensure_summaries(db, [item], prefs, settings, allow_llm=False)
        summary = summaries.get((item.source, item.external_id))
        scored = score_item(item, prefs)
        zone = ZoneInfo(prefs.timezone)
        moment = item.published_at or item.first_seen_at
        return _render(
            templates,
            request,
            "item.html",
            {
                "missing": False,
                "title": item.title,
                "url": item.url if item.url.startswith(("http://", "https://")) else "",
                "source_label": source_label(item),
                "language": item.language,
                "time_label": moment.astimezone(zone).strftime("%Y-%m-%d %H:%M") if moment else "",
                "score": f"{scored.score:.1f}" if scored else "",
                "matched": scored.matched if scored else [],
                "blurb": summary.short if summary else item.summary,
                "detail": summary.long if summary else item.summary,
                "takeaways": summary.takeaways if summary else [],
                "original": item.summary,
                "summary_label": "摘要" if summary and summary.provider == "llm" else "摘录",
            },
        )

    @app.get("/login")
    def login_form(request: Request):
        settings = request.app.state.settings
        if not settings.admin_password or request.session.get("admin"):
            return RedirectResponse(_safe_next(request.query_params.get("next") or "/settings"), status_code=303)
        return _render(
            templates,
            request,
            "login.html",
            {"csrf": _csrf(request), "next": _safe_next(request.query_params.get("next") or "/settings"), "error": ""},
        )

    @app.post("/login")
    async def login_submit(request: Request):
        settings = request.app.state.settings
        form = await request.form()
        nxt = _safe_next(str(form.get("next") or "/settings"))
        if not settings.admin_password:
            return RedirectResponse(nxt, status_code=303)
        if not _csrf_ok(request, form.get("csrf")):
            return _render(
                templates,
                request,
                "login.html",
                {"csrf": _csrf(request), "next": nxt, "error": "页面已过期，请再试一次"},
                status_code=400,
            )
        password = str(form.get("password") or "")
        if not password or not hmac.compare_digest(password, settings.admin_password):
            return _render(
                templates,
                request,
                "login.html",
                {"csrf": _csrf(request), "next": nxt, "error": "密码不正确"},
                status_code=401,
            )
        request.session["admin"] = True
        return RedirectResponse(nxt, status_code=303)

    @app.post("/logout")
    async def logout(request: Request):
        form = await request.form()
        if _csrf_ok(request, form.get("csrf")):
            request.session.clear()
        return RedirectResponse("/", status_code=303)

    @app.get("/settings")
    def settings_page(request: Request):
        denied = _guard_admin(request, request.app.state.settings)
        if denied is not None:
            return denied
        return _render(templates, request, "settings.html", _settings_context(request))

    @app.post("/settings")
    async def save_settings(request: Request):
        denied = _guard_admin(request, request.app.state.settings)
        if denied is not None:
            return denied
        form = await request.form()
        draft = _draft_from_form(form)
        if not _csrf_ok(request, form.get("csrf")):
            context = _settings_context(request, draft=draft, errors=["页面已过期，请刷新后重试"])
            return _render(templates, request, "settings.html", context, status_code=400)
        prefs, errors = parse_preferences(draft)
        if prefs is None:
            context = _settings_context(request, draft=draft, errors=errors)
            return _render(templates, request, "settings.html", context, status_code=400)
        db = request.app.state.db
        db.save_preferences(prefs)
        reschedule(request.app)
        action = str(form.get("action") or "save")
        try:
            if action == "fetch":
                async with request.app.state.fetch_lock:
                    report = await fetch_and_store(db, request.app.state.settings)
                level = "warn" if any(not source.ok for source in report.sources) else "ok"
                _set_flash(request, report.summary(), level)
            elif action == "test":
                async with request.app.state.fetch_lock:
                    report = await push_digest(db, request.app.state.settings)
                if report.attempted_failures:
                    level = "err"
                elif report.attempted_successes:
                    level = "ok"
                else:
                    level = "warn"
                _set_flash(request, report.summary(), level)
            else:
                _set_flash(request, "设置已保存", "ok")
        except Exception as exc:
            logger.exception("设置页操作失败")
            _set_flash(request, f"操作没有完成：{exc}", "err")
        return RedirectResponse("/settings", status_code=303)


def _settings_context(request: Request, draft: dict | None = None, errors: list[str] | None = None) -> dict:
    db = request.app.state.db
    settings = request.app.state.settings
    prefs = db.get_preferences()
    zone = ZoneInfo(prefs.timezone)
    fields = _fields_from_prefs(prefs)
    if draft:
        fields.update(draft)
    zones = list(TIMEZONES)
    current_zone = str(fields.get("timezone") or prefs.timezone)
    if current_zone not in zones:
        zones.insert(0, current_zone)
    return {
        "csrf": _csrf(request),
        "errors": errors or [],
        "fields": fields,
        "catalog": CATALOG,
        "timezones": zones,
        "channels": [
            {
                "id": channel.id,
                "label": channel.label,
                "configured": channel.configured(settings),
                "hint": CHANNEL_HINTS.get(channel.id, ""),
            }
            for channel in CHANNELS
        ],
        "password_set": bool(settings.admin_password),
        "protect_site": settings.protect_site,
        "fetch_run": _present_fetch_run(db.latest_fetch_run(), zone),
        "last_push": _present_push(db.last_push(), zone),
        "llm_ready": bool(settings.openai_api_key),
        "llm_model_default": settings.openai_model,
    }


def _fields_from_prefs(prefs: Preferences) -> dict:
    return {
        "keywords": format_keywords(prefs),
        "blocked": format_blocked(prefs),
        "languages": format_languages(prefs),
        "rss_feeds": format_feeds(prefs),
        "sources": list(prefs.enabled_sources),
        "channels": [key for key, enabled in prefs.channels.items() if enabled],
        "items_per_digest": prefs.items_per_digest,
        "digest_hour": prefs.digest_hour,
        "digest_minute": prefs.digest_minute,
        "timezone": prefs.timezone,
        "digest_window_hours": prefs.digest_window_hours,
        "llm_summaries": prefs.llm_summaries,
        "llm_model": prefs.llm_model,
    }


def _draft_from_form(form) -> dict:
    return {
        "keywords": str(form.get("keywords") or ""),
        "blocked": str(form.get("blocked") or ""),
        "languages": str(form.get("languages") or ""),
        "rss_feeds": str(form.get("rss_feeds") or ""),
        "sources": list(form.getlist("sources")),
        "channels": list(form.getlist("channels")),
        "items_per_digest": str(form.get("items_per_digest") or ""),
        "digest_hour": str(form.get("digest_hour") or ""),
        "digest_minute": str(form.get("digest_minute") or ""),
        "timezone": str(form.get("timezone") or ""),
        "digest_window_hours": str(form.get("digest_window_hours") or ""),
        "llm_summaries": str(form.get("llm_summaries") or "").lower() in {"1", "on", "true", "yes"},
        "llm_model": str(form.get("llm_model") or ""),
    }


def _row(scored, zone: ZoneInfo, summary=None) -> dict:
    item = scored.item
    moment = item.published_at or item.first_seen_at
    parts = []
    if scored.keyword_score:
        parts.append(f"关键词 +{scored.keyword_score:.0f}")
    if scored.language_score:
        parts.append(f"语言 +{scored.language_score:.0f}")
    parts.append(f"热度 {scored.popularity_score:.1f}")
    blurb = summary.short if summary else item.summary
    detail = summary.long if summary else ""
    if detail == blurb:
        detail = ""
    original = item.summary if item.summary and item.summary not in {blurb, detail} else ""
    return {
        "title": item.title,
        "url": item.url if item.url.startswith(("http://", "https://")) else "",
        "source_label": source_label(item),
        "score": f"{scored.score:.1f}",
        "breakdown": " · ".join(parts),
        "popularity": f"{int(round(item.popularity)):,}",
        "blurb": blurb,
        "detail": detail,
        "takeaways": summary.takeaways if summary else [],
        "original": original,
        "summary_label": "摘要" if summary and summary.provider == "llm" else "摘录",
        "detail_href": f"/items/{item.id}" if item.id else "",
        "matched": scored.matched,
        "language": item.language,
        "time_label": moment.astimezone(zone).strftime("%m-%d %H:%M") if moment else "刚刚收录",
        "hot": bool(scored.matched),
    }


def _present_fetch_run(report: dict | None, zone: ZoneInfo) -> dict | None:
    if not report:
        return None
    sources = []
    for source in report.get("sources") or []:
        if not isinstance(source, dict):
            continue
        error = str(source.get("error") or "")
        sources.append(
            {
                "label": source.get("label") or source.get("source_id") or "来源",
                "count": source.get("count") or 0,
                "ok": bool(source.get("ok")),
                "error": error[:180],
            }
        )
    return {
        "inserted": report.get("inserted") or 0,
        "updated": report.get("updated") or 0,
        "finished_label": _format_stamp(report.get("finished_at"), zone),
        "sources": sources,
    }


def _present_push(payload: dict | None, zone: ZoneInfo) -> dict | None:
    if not payload:
        return None
    return {
        "summary": str(payload.get("summary") or ""),
        "when": _format_stamp(payload.get("at"), zone),
    }


def _format_stamp(value: str | None, zone: ZoneInfo) -> str:
    parsed = from_iso(value)
    if parsed is None:
        return ""
    return parsed.astimezone(zone).strftime("%m-%d %H:%M")


def _render(templates: Jinja2Templates, request: Request, name: str, context: dict, status_code: int = 200):
    payload = {"flash": _pop_flash(request), **context}
    return templates.TemplateResponse(request, name, payload, status_code=status_code)


def _guard_site(request: Request, settings):
    if settings.protect_site and settings.admin_password and not request.session.get("admin"):
        target = request.url.path
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return RedirectResponse(f"/login?next={quote(target, safe='/?=&')}", status_code=303)
    return None


def _guard_admin(request: Request, settings):
    if settings.admin_password and not request.session.get("admin"):
        return RedirectResponse("/login?next=/settings", status_code=303)
    return None


def _safe_next(value: str) -> str:
    if value.startswith("/") and not value.startswith("//") and not value.startswith("/\\"):
        return value
    return "/settings"


def _csrf(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(24)
        request.session["csrf"] = token
    return token


def _csrf_ok(request: Request, provided) -> bool:
    expected = str(request.session.get("csrf") or "")
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, str(provided))


def _set_flash(request: Request, text: str, level: str) -> None:
    request.session["flash"] = {"text": text, "level": level}


def _pop_flash(request: Request):
    return request.session.pop("flash", None)
