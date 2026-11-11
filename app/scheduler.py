"""进程内的每日定时任务。服务停着的时候不会补跑，机器需要一直开着。"""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.pipeline import fetch_and_store, push_digest

logger = logging.getLogger(__name__)
JOB_ID = "daily-digest"


def start_scheduler(app) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    prefs = app.state.db.get_preferences()
    scheduler.add_job(
        _run,
        _trigger(prefs),
        args=[app],
        id=JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.start()
    job = scheduler.get_job(JOB_ID)
    if job is not None:
        logger.info("每日早报已排程，下次运行 %s", job.next_run_time)
    return scheduler


def reschedule(app) -> None:
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is None:
        return
    prefs = app.state.db.get_preferences()
    if scheduler.get_job(JOB_ID) is None:
        scheduler.add_job(
            _run,
            _trigger(prefs),
            args=[app],
            id=JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
    else:
        scheduler.reschedule_job(JOB_ID, trigger=_trigger(prefs))
    job = scheduler.get_job(JOB_ID)
    if job is not None:
        logger.info("每日早报已改为 %02d:%02d %s，下次运行 %s", prefs.digest_hour, prefs.digest_minute, prefs.timezone, job.next_run_time)


def _trigger(prefs):
    return CronTrigger(
        hour=prefs.digest_hour,
        minute=prefs.digest_minute,
        timezone=ZoneInfo(prefs.timezone),
    )


async def _run(app) -> None:
    logger.info("开始每日抓取与推送")
    try:
        async with app.state.fetch_lock:
            await fetch_and_store(app.state.db, app.state.settings)
            await push_digest(app.state.db, app.state.settings)
    except Exception:
        logger.exception("每日任务失败")
