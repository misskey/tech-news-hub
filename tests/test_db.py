from datetime import datetime, timezone

from app.db import Database
from app.models import NewsItem


def test_upsert_dedupes_same_source_identity(tmp_path):
    db = Database(tmp_path / "news.db")
    db.init()
    first = NewsItem(
        source="github",
        external_id="owner/repo",
        title="owner/repo",
        url="https://github.com/owner/repo",
        popularity=10,
        language="Python",
    )
    inserted, updated = db.upsert_items([first])
    assert (inserted, updated) == (1, 0)
    stored = db.items_since(datetime(2020, 1, 1, tzinfo=timezone.utc))
    seen = stored[0].first_seen_at
    again = NewsItem(
        source="github",
        external_id="owner/repo",
        title="owner/repo",
        url="https://github.com/owner/repo",
        popularity=99,
        language="Python",
    )
    inserted, updated = db.upsert_items([again, again])
    assert (inserted, updated) == (0, 1)
    assert db.count_items() == 1
    stored = db.items_since(datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert stored[0].popularity == 99
    assert stored[0].first_seen_at == seen

    other = NewsItem(
        source="hackernews",
        external_id="owner/repo",
        title="same id elsewhere",
        url="https://news.ycombinator.com/item?id=1",
        popularity=1,
    )
    db.upsert_items([other])
    assert db.count_items() == 2
