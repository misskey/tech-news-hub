"""从环境变量和可选的 .env 读取运行配置。密钥只走环境变量，不进数据库。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path) -> None:
    """把 .env 里尚未设置的变量放进环境。已有的环境变量优先。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    secret_key: str
    admin_password: str
    protect_site: bool
    scheduler_enabled: bool
    fetch_timeout: float
    hn_story_limit: int
    log_level: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_to: str
    smtp_tls: bool
    smtp_ssl: bool
    serverchan_sendkey: str
    telegram_bot_token: str
    telegram_chat_id: str
    wecom_webhook: str
    feishu_webhook: str
    feishu_secret: str

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(Path.cwd() / ".env")
        load_dotenv(ROOT / ".env")
        data_dir = Path(os.environ.get("DATA_DIR") or ROOT / "data").expanduser()
        database = os.environ.get("DATABASE_PATH")
        database_path = Path(database).expanduser() if database else data_dir / "news.db"
        return cls(
            data_dir=data_dir,
            database_path=database_path,
            secret_key=(os.environ.get("SECRET_KEY") or "").strip(),
            admin_password=os.environ.get("ADMIN_PASSWORD") or "",
            protect_site=_bool("PROTECT_SITE", False),
            scheduler_enabled=_bool("SCHEDULER_ENABLED", True),
            fetch_timeout=_float("FETCH_TIMEOUT", 20),
            hn_story_limit=max(5, min(_int("HN_STORY_LIMIT", 30), 80)),
            log_level=(os.environ.get("LOG_LEVEL") or "INFO").strip() or "INFO",
            smtp_host=(os.environ.get("SMTP_HOST") or "").strip(),
            smtp_port=_int("SMTP_PORT", 587),
            smtp_user=(os.environ.get("SMTP_USER") or "").strip(),
            smtp_password=os.environ.get("SMTP_PASSWORD") or "",
            smtp_from=(os.environ.get("SMTP_FROM") or "").strip(),
            smtp_to=(os.environ.get("SMTP_TO") or "").strip(),
            smtp_tls=_bool("SMTP_TLS", True),
            smtp_ssl=_bool("SMTP_SSL", False),
            serverchan_sendkey=(os.environ.get("SERVERCHAN_SENDKEY") or "").strip(),
            telegram_bot_token=(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip(),
            telegram_chat_id=(os.environ.get("TELEGRAM_CHAT_ID") or "").strip(),
            wecom_webhook=(os.environ.get("WECOM_WEBHOOK") or "").strip(),
            feishu_webhook=(os.environ.get("FEISHU_WEBHOOK") or "").strip(),
            feishu_secret=(os.environ.get("FEISHU_SECRET") or "").strip(),
        )


def configure_logging(level: str) -> None:
    import logging

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
