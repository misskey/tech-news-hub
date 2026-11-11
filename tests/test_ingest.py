import asyncio

from app.fetchers.base import FetchOutcome
from app.ingest import collect
from app.models import NewsItem
from app.prefs import default_preferences


class Boom:
    source_id = "boom"
    label = "坏源"

    async def run(self, client, prefs):
        raise RuntimeError("down")


class Ok:
    source_id = "ok"
    label = "好源"

    async def run(self, client, prefs):
        return FetchOutcome(
            items=[
                NewsItem(
                    source="hackernews",
                    external_id="1",
                    title="Still here",
                    url="https://example.com/ok",
                )
            ]
        )


def test_failed_source_is_skipped():
    items, reports = asyncio.run(collect([Boom(), Ok()], None, default_preferences()))
    assert [item.title for item in items] == ["Still here"]
    assert reports[0].ok is False
    assert "down" in reports[0].error
    assert reports[1].ok is True
    assert reports[1].count == 1
