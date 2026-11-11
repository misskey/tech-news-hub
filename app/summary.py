"""条目摘要和每日简报。

有 OpenAI 兼容接口时用它写中文。没有密钥、用户关掉，或接口失败时，
改用标题和原文摘录，保证抓取和页面都能继续。
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime

from app.llm import SYSTEM_BRIEFING, SYSTEM_ITEMS, ChatClient, parse_json_object
from app.models import Briefing, ItemSummary, NewsItem, Preferences, ScoredItem
from app.sources import source_label

logger = logging.getLogger(__name__)

LLM_BUDGET = 20
_CJK = re.compile(r"[\u3400-\u9fff]")
_NEW = re.compile(
    r"(发布|开源|推出|上线)|(\b(release[ds]?|launch(?:ed)?|announc(?:e|ed|ing)|introduc(?:e|ing|ed)|open[\s-]source)\b)",
    re.I,
)
_TERMS = (
    "TypeScript",
    "JavaScript",
    "PostgreSQL",
    "WebAssembly",
    "Kubernetes",
    "DeepSeek",
    "Anthropic",
    "OpenAI",
    "FastAPI",
    "Next.js",
    "Python",
    "SQLite",
    "Docker",
    "Claude",
    "Gemini",
    "Llama",
    "Qwen",
    "React",
    "Svelte",
    "Vue",
    "Rust",
    "Java",
    "Kotlin",
    "Swift",
    "Ruby",
    "Redis",
    "Linux",
    "GitHub",
    "Android",
    "Transformer",
    "CUDA",
    "WASM",
    "MCP",
    "RAG",
    "LLM",
    "GPT",
    "C++",
    "C#",
    "Go",
    "PHP",
)


def content_hash(item: NewsItem) -> str:
    blob = f"{item.title}\n{item.summary}"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def extractive_summary(item: NewsItem) -> ItemSummary:
    label = source_label(item)
    title = " ".join((item.title or "").split())
    body = " ".join((item.summary or "").split())
    sentences = _sentences(body)
    takeaways = _takeaways(f"{title}\n{body}", item.language)
    if not sentences:
        text = f"这条来自{label}，标题是「{title}」。原文没有附带简介。"
        return ItemSummary(text, text, takeaways, "extractive")
    short_src = _clip(" ".join(sentences[:2]), 160)
    long_src = _clip(" ".join(sentences[:4]), 360)
    if _CJK.search(short_src):
        short = _clip(short_src, 90)
        long = long_src
    else:
        kind = "新发布或新工具" if looks_new(item) else "内容"
        short = f"{label}的这条{kind}：{title}。摘录：{_clip(sentences[0], 80)}"
        long = _clip(f"{title}。{long_src}", 360)
    return ItemSummary(short, long, takeaways, "extractive")


def looks_new(item: NewsItem) -> bool:
    return _NEW.search(f"{item.title}\n{item.summary}") is not None


def assemble_briefing(scored: list[ScoredItem], summaries: dict[tuple[str, str], ItemSummary]) -> Briefing:
    """不访问网络。用主题计数和标题拼一份一分钟能读完的中文简报。"""
    if not scored:
        return Briefing("今天还没有新内容。", [], "extractive")
    themes: dict[str, int] = {}
    for item in scored:
        for name in item.matched:
            themes[name] = themes.get(name, 0) + 1
        summary = summaries.get((item.item.source, item.item.external_id))
        if summary:
            for name in summary.takeaways:
                themes[name] = themes.get(name, 0) + 1
    top = sorted(themes.items(), key=lambda pair: (-pair[1], pair[0]))[:3]
    if top:
        theme_text = "、".join(f"{name}（{count}）" for name, count in top)
        overview = f"今天有 {len(scored)} 条新内容，比较集中的是{theme_text}。"
    else:
        overview = f"今天有 {len(scored)} 条新内容，主题比较散，可以先看热度靠前的几条。"
    highlights: list[str] = []
    ordered = sorted(scored, key=lambda item: (looks_new(item.item), bool(item.matched), item.score), reverse=True)
    seen: set[tuple[str, str]] = set()
    for item in ordered:
        key = (item.item.source, item.item.external_id)
        if key in seen:
            continue
        seen.add(key)
        summary = summaries.get(key)
        suffix = ""
        if summary and summary.takeaways:
            suffix = "，涉及" + "、".join(summary.takeaways[:3])
        prefix = "新发布：" if looks_new(item.item) else ""
        highlights.append(f"{prefix}{source_label(item.item)}《{_clip(item.item.title, 42)}》{suffix}")
        if len(highlights) >= 5:
            break
    return Briefing(overview, highlights, "extractive")


def ensure_summaries(db, items: list[NewsItem], prefs: Preferences, settings, *, allow_llm: bool = True, chat=None) -> dict[tuple[str, str], ItemSummary]:
    unique: dict[tuple[str, str], NewsItem] = {}
    for item in items:
        unique[(item.source, item.external_id)] = item
    if not unique:
        return {}
    cached = db.load_summaries(list(unique))
    want_llm = allow_llm and _llm_wanted(prefs, settings)
    model = _model_name(prefs, settings)
    ready: dict[tuple[str, str], ItemSummary] = {}
    pending_llm: list[NewsItem] = []
    pending_plain: list[NewsItem] = []
    for key, item in unique.items():
        row = cached.get(key)
        digest = content_hash(item)
        if row and row["content_hash"] == digest and (row["provider"] == "llm" or not want_llm):
            ready[key] = _summary_from_row(row)
            continue
        if want_llm and len(pending_llm) < LLM_BUDGET:
            pending_llm.append(item)
        else:
            pending_plain.append(item)
    produced: dict[tuple[str, str], ItemSummary] = {}
    if pending_llm:
        produced.update(_llm_summaries(pending_llm, settings, model, chat))
    for item in pending_plain:
        produced[(item.source, item.external_id)] = extractive_summary(item)
    if produced:
        db.save_summaries(produced, {key: content_hash(unique[key]) for key in produced})
    ready.update(produced)
    return ready


def ensure_briefing(db, scored: list[ScoredItem], summaries: dict[tuple[str, str], ItemSummary], prefs: Preferences, settings, *, now: datetime, allow_llm: bool = True, chat=None) -> Briefing:
    from zoneinfo import ZoneInfo

    local_day = now.astimezone(ZoneInfo(prefs.timezone)).strftime("%Y-%m-%d")
    fingerprint = _fingerprint(scored, summaries, prefs, settings)
    cached = db.load_briefing(local_day)
    want_llm = allow_llm and _llm_wanted(prefs, settings) and bool(scored)
    if cached and cached["fingerprint"] == fingerprint and (cached["provider"] == "llm" or not want_llm):
        return _briefing_from_row(cached)
    briefing = assemble_briefing(scored, summaries)
    if want_llm:
        try:
            client = chat or ChatClient(settings.openai_api_key, settings.openai_base_url, _model_name(prefs, settings))
            payload = parse_json_object(client.complete([
                {"role": "system", "content": SYSTEM_BRIEFING},
                {"role": "user", "content": _briefing_prompt(scored, summaries)},
            ]))
            upgraded = _briefing_from_payload(payload, client.model)
            if upgraded is not None:
                briefing = upgraded
        except Exception:
            logger.exception("每日简报生成失败，改用摘录")
    db.save_briefing(local_day, fingerprint, briefing)
    return briefing


def _llm_summaries(items: list[NewsItem], settings, model: str, chat) -> dict[tuple[str, str], ItemSummary]:
    client = chat or ChatClient(settings.openai_api_key, settings.openai_base_url, model)
    produced: dict[tuple[str, str], ItemSummary] = {}
    for batch in _chunks(items, 4):
        try:
            payload = parse_json_object(client.complete([
                {"role": "system", "content": SYSTEM_ITEMS},
                {"role": "user", "content": _items_prompt(batch)},
            ]))
            produced.update(_summaries_from_payload(batch, payload, model))
        except Exception:
            logger.exception("一批摘要生成失败，这批改用摘录")
        for item in batch:
            key = (item.source, item.external_id)
            if key not in produced:
                produced[key] = extractive_summary(item)
    return produced


def _summaries_from_payload(items: list[NewsItem], payload: dict, model: str) -> dict[tuple[str, str], ItemSummary]:
    found: dict[tuple[str, str], ItemSummary] = {}
    rows = payload.get("items")
    if not isinstance(rows, list):
        return found
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            index = int(row.get("index"))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(items):
            continue
        short = _clip(str(row.get("short") or "").strip(), 180)
        long = _clip(str(row.get("long") or "").strip(), 500)
        if not short:
            continue
        takeaways = []
        for value in row.get("takeaways") or []:
            text = str(value).strip()[:40]
            if text and text not in takeaways:
                takeaways.append(text)
            if len(takeaways) >= 6:
                break
        item = items[index]
        found[(item.source, item.external_id)] = ItemSummary(short, long or short, takeaways, "llm", model)
    return found


def _briefing_from_payload(payload: dict, model: str) -> Briefing | None:
    overview = _clip(str(payload.get("overview") or "").strip(), 400)
    if not overview:
        return None
    highlights = []
    for value in payload.get("highlights") or []:
        text = str(value).strip()
        if text:
            highlights.append(_clip(text, 120))
        if len(highlights) >= 6:
            break
    return Briefing(overview, highlights, "llm", model)


def _items_prompt(items: list[NewsItem]) -> str:
    blocks = []
    for index, item in enumerate(items):
        blocks.append(
            f"[{index}] 来源：{source_label(item)}\n标题：{item.title}\n摘录：{_clip(item.summary, 500) or '（无）'}"
        )
    return "\n\n".join(blocks)


def _briefing_prompt(scored: list[ScoredItem], summaries: dict[tuple[str, str], ItemSummary]) -> str:
    lines = []
    for item in scored[:12]:
        summary = summaries.get((item.item.source, item.item.external_id))
        short = summary.short if summary else item.item.title
        lines.append(f"- {source_label(item.item)}｜{item.item.title}｜{short}")
    return f"今日共 {len(scored)} 条，下面是要优先看的：\n" + "\n".join(lines)


def _llm_wanted(prefs: Preferences, settings) -> bool:
    return bool(getattr(settings, "openai_api_key", "") and prefs.llm_summaries)


def _model_name(prefs: Preferences, settings) -> str:
    chosen = (prefs.llm_model or "").strip()
    if chosen:
        return chosen
    return getattr(settings, "openai_model", "") or "gpt-4o-mini"


def _fingerprint(scored: list[ScoredItem], summaries: dict[tuple[str, str], ItemSummary], prefs: Preferences, settings) -> str:
    parts = ["v2", _model_name(prefs, settings), str(len(scored))]
    for item in scored[:12]:
        summary = summaries.get((item.item.source, item.item.external_id))
        parts.append(
            f"{item.item.source}:{item.item.external_id}:{content_hash(item.item)}:"
            f"{','.join(item.matched)}:{summary.short if summary else ''}"
        )
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:20]


def _summary_from_row(row: dict) -> ItemSummary:
    return ItemSummary(row["short"], row["long"], list(row["takeaways"]), row["provider"], row.get("model") or "")


def _briefing_from_row(row: dict) -> Briefing:
    return Briefing(row["overview"], list(row["highlights"]), row["provider"], row.get("model") or "")


def _sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[。！？.!?])\s+", text)
    return [part.strip() for part in parts if part.strip()]


def _takeaways(text: str, language: str) -> list[str]:
    found: list[str] = []
    for term in _TERMS:
        if _mentioned(text, term) and term not in found:
            found.append(term)
        if len(found) >= 6:
            break
    if language and language not in found and _mentioned(text, language):
        found.append(language)
    return found[:6]


def _mentioned(text: str, term: str) -> bool:
    if not term:
        return False
    if _CJK.search(term):
        return term in text
    pattern = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
    return re.search(pattern, text, re.I) is not None


def _clip(text: str, limit: int) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "…"


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]
