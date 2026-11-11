"""SQLite 存储。同一来源的同一外部 ID 只保留一行，重复抓取会更新热度而不是再插一条。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from app.models import NewsItem, Preferences
from app.prefs import default_preferences, preferences_from_dict


def to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class Database:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=5000")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def init(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    author TEXT NOT NULL DEFAULT '',
                    language TEXT NOT NULL DEFAULT '',
                    popularity REAL NOT NULL DEFAULT 0,
                    published_at TEXT,
                    fetched_at TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    extra_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(source, external_id)
                );
                CREATE INDEX IF NOT EXISTS idx_items_first_seen ON items(first_seen_at);
                CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at);
                CREATE INDEX IF NOT EXISTS idx_items_url ON items(url);

                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS fetch_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    report_json TEXT NOT NULL
                );
                """
            )

    def get_meta(self, key: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO meta(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_preferences(self) -> Preferences:
        raw = self.get_meta("preferences")
        if not raw:
            prefs = default_preferences()
            self.save_preferences(prefs)
            return prefs
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return default_preferences()
        return preferences_from_dict(data)

    def save_preferences(self, prefs: Preferences) -> None:
        self.set_meta("preferences", json.dumps(prefs.to_dict(), ensure_ascii=False))

    def upsert_items(self, items: list[NewsItem]) -> tuple[int, int]:
        merged: dict[tuple[str, str], NewsItem] = {}
        for item in items:
            normalized = _clamp_item(item)
            if not normalized.title or not normalized.url or not normalized.external_id:
                continue
            if not normalized.url.startswith(("http://", "https://")):
                continue
            merged[(normalized.source, normalized.external_id)] = normalized
        if not merged:
            return 0, 0
        now = to_iso(datetime.now(timezone.utc))
        inserted = 0
        updated = 0
        with self.connect() as connection:
            for item in merged.values():
                existing = connection.execute(
                    "SELECT id, first_seen_at FROM items WHERE source = ? AND external_id = ?",
                    (item.source, item.external_id),
                ).fetchone()
                published = to_iso(item.published_at) if item.published_at else None
                extra = json.dumps(item.extra or {}, ensure_ascii=False)
                if existing:
                    connection.execute(
                        """
                        UPDATE items
                        SET title = ?, url = ?, summary = ?, author = ?, language = ?,
                            popularity = ?, published_at = ?, fetched_at = ?, extra_json = ?
                        WHERE source = ? AND external_id = ?
                        """,
                        (
                            item.title,
                            item.url,
                            item.summary,
                            item.author,
                            item.language,
                            item.popularity,
                            published,
                            now,
                            extra,
                            item.source,
                            item.external_id,
                        ),
                    )
                    updated += 1
                else:
                    connection.execute(
                        """
                        INSERT INTO items (
                            source, external_id, title, url, summary, author, language,
                            popularity, published_at, fetched_at, first_seen_at, extra_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item.source,
                            item.external_id,
                            item.title,
                            item.url,
                            item.summary,
                            item.author,
                            item.language,
                            item.popularity,
                            published,
                            now,
                            now,
                            extra,
                        ),
                    )
                    inserted += 1
        return inserted, updated

    def items_since(self, since: datetime, limit: int = 500) -> list[NewsItem]:
        stamp = to_iso(since)
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM items
                WHERE first_seen_at >= ? OR (published_at IS NOT NULL AND published_at >= ?)
                ORDER BY COALESCE(published_at, first_seen_at) DESC
                LIMIT ?
                """,
                (stamp, stamp, limit),
            ).fetchall()
        return [_row_to_item(row) for row in rows]

    def count_items(self) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM items").fetchone()
        return int(row["n"])

    def add_fetch_run(self, started_at: datetime, report: dict) -> None:
        finished = datetime.now(timezone.utc)
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO fetch_runs(started_at, finished_at, report_json) VALUES(?, ?, ?)",
                (to_iso(started_at), to_iso(finished), json.dumps(report, ensure_ascii=False)),
            )
            connection.execute(
                """
                DELETE FROM fetch_runs
                WHERE id NOT IN (SELECT id FROM fetch_runs ORDER BY id DESC LIMIT 30)
                """
            )

    def latest_fetch_run(self) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT started_at, finished_at, report_json FROM fetch_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        try:
            report = json.loads(row["report_json"])
        except json.JSONDecodeError:
            report = {}
        report["started_at"] = row["started_at"]
        report["finished_at"] = row["finished_at"]
        return report

    def set_last_push(self, payload: dict) -> None:
        self.set_meta("last_push", json.dumps(payload, ensure_ascii=False))

    def last_push(self) -> dict | None:
        raw = self.get_meta("last_push")
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None


def _clamp_item(item: NewsItem) -> NewsItem:
    item.title = (item.title or "").strip()[:300]
    item.summary = (item.summary or "").strip()[:500]
    item.url = (item.url or "").strip()[:1000]
    item.author = (item.author or "").strip()[:80]
    item.language = (item.language or "").strip()[:40]
    item.external_id = str(item.external_id or "").strip()[:300]
    item.source = (item.source or "").strip()[:80]
    try:
        item.popularity = float(item.popularity or 0)
    except (TypeError, ValueError):
        item.popularity = 0
    if item.popularity < 0:
        item.popularity = 0
    return item


def _row_to_item(row: sqlite3.Row) -> NewsItem:
    try:
        extra = json.loads(row["extra_json"] or "{}")
    except json.JSONDecodeError:
        extra = {}
    if not isinstance(extra, dict):
        extra = {}
    return NewsItem(
        source=row["source"],
        external_id=row["external_id"],
        title=row["title"],
        url=row["url"],
        summary=row["summary"] or "",
        author=row["author"] or "",
        language=row["language"] or "",
        popularity=float(row["popularity"] or 0),
        published_at=from_iso(row["published_at"]),
        extra=extra,
        id=row["id"],
        first_seen_at=from_iso(row["first_seen_at"]),
        fetched_at=from_iso(row["fetched_at"]),
    )
