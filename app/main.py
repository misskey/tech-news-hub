"""FastAPI 入口。浏览、设置、定时抓取和推送都在同一个进程里。"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from app import __version__
from app.api import router as client_router
from app.config import ROOT, Settings, configure_logging
from app.db import Database
from app.routes import register
from app.scheduler import start_scheduler

logger = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(ROOT / "templates"))
STATIC_DIR = ROOT / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)
    secret = _resolve_secret(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        import asyncio

        db = Database(settings.database_path)
        db.init()
        app.state.db = db
        app.state.fetch_lock = asyncio.Lock()
        app.state.scheduler = None
        if not settings.admin_password:
            logger.warning("未设置 ADMIN_PASSWORD，设置页目前没有密码保护")
        if settings.scheduler_enabled:
            app.state.scheduler = start_scheduler(app)
            logger.info("内置调度器已启动")
        else:
            logger.info("内置调度器已关闭，可以用命令行或系统 cron 触发")
        yield
        scheduler = app.state.scheduler
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="科技早报", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie="tnh_session",
        max_age=14 * 24 * 3600,
        same_site="lax",
        https_only=False,
    )
    register(app, TEMPLATES)
    app.include_router(client_router)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


def _resolve_secret(settings: Settings) -> str:
    if settings.secret_key:
        return settings.secret_key
    path = Path(settings.data_dir) / "secret_key"
    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    path.write_text(key, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


app = create_app()
