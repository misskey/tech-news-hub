"""手动抓取和推送。

    python -m app.cli fetch
    python -m app.cli push
    python -m app.cli run
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.config import Settings, configure_logging
from app.db import Database
from app.pipeline import fetch_and_store, push_digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tech-news-hub", description="抓取科技资讯并推送早报")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch", help="抓取已启用的来源并写入数据库")
    sub.add_parser("push", help="按已保存的偏好生成并推送早报")
    sub.add_parser("run", help="先抓取，再推送")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    configure_logging(settings.log_level)
    db = Database(settings.database_path)
    db.init()

    if args.command == "fetch":
        report = asyncio.run(fetch_and_store(db, settings))
        _print_fetch(report)
        return 0 if report.any_success else 1
    if args.command == "push":
        report = asyncio.run(push_digest(db, settings))
        print(report.summary())
        return 1 if report.attempted_failures and not report.attempted_successes else 0

    fetch_report = asyncio.run(fetch_and_store(db, settings))
    _print_fetch(fetch_report)
    if not fetch_report.any_success:
        return 1
    push_report = asyncio.run(push_digest(db, settings))
    print(push_report.summary())
    if push_report.attempted_failures and not push_report.attempted_successes:
        return 1
    return 0


def _print_fetch(report) -> None:
    print(report.summary())
    for source in report.sources:
        status = "成功" if source.ok else "失败"
        line = f"- {source.label}：{status}，{source.count} 条"
        if source.error:
            line += f"（{source.error}）"
        print(line)


if __name__ == "__main__":
    sys.exit(main())
