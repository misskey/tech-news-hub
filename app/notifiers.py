"""推送渠道。密钥来自环境变量，是否启用由设置页的开关决定。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import smtplib
import time
from email.message import EmailMessage
from typing import Protocol

import httpx

from app.config import Settings
from app.digest import Digest, render_html, render_markdown, render_plain, telegram_messages

logger = logging.getLogger(__name__)


class Channel(Protocol):
    id: str
    label: str

    def configured(self, settings: Settings) -> bool: ...

    async def send(self, digest: Digest, settings: Settings) -> None: ...


def feishu_sign(timestamp: str, secret: str) -> str:
    payload = f"{timestamp}\n{secret}"
    digest = hmac.new(payload.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def serverchan_form(digest: Digest) -> dict[str, str]:
    title = " ".join(digest.title.split())[:32] or "科技早报"
    return {"title": title, "desp": render_markdown(digest)[:30000]}


def wecom_body(digest: Digest) -> dict:
    content = render_markdown(digest)
    if len(content) > 3500:
        content = content[:3500].rstrip() + "\n\n…内容过长已截断"
    return {"msgtype": "markdown", "markdown": {"content": content}}


def feishu_body(digest: Digest, secret: str = "", timestamp: str | None = None) -> dict:
    content = []
    if digest.overview:
        content.append([{"tag": "text", "text": digest.overview[:500]}])
    if digest.highlights:
        content.append([{"tag": "text", "text": "今日新技术看点：" + "；".join(digest.highlights[:5])}])
    for entry in digest.entries:
        note = f"  · {entry.source_label} · {entry.score:.0f}"
        if entry.summary:
            note += f"。{entry.summary[:80]}"
        line = [
            {"tag": "a", "text": entry.title[:120], "href": entry.url},
            {"tag": "text", "text": note},
        ]
        content.append(line)
    if not content:
        content = [[{"tag": "text", "text": "这个时间窗口里没有可推送的内容。"}]]
    body: dict = {
        "msg_type": "post",
        "content": {"post": {"zh_cn": {"title": digest.title[:100], "content": content}}},
    }
    if secret:
        stamp = timestamp or str(int(time.time()))
        body["timestamp"] = stamp
        body["sign"] = feishu_sign(stamp, secret)
    return body


class EmailChannel:
    id = "email"
    label = "邮件"

    def configured(self, settings: Settings) -> bool:
        return bool(settings.smtp_host and settings.smtp_to)

    async def send(self, digest: Digest, settings: Settings) -> None:
        await asyncio.to_thread(_send_email, digest, settings)


class ServerChanChannel:
    id = "serverchan"
    label = "Server酱"

    def configured(self, settings: Settings) -> bool:
        return bool(settings.serverchan_sendkey)

    async def send(self, digest: Digest, settings: Settings) -> None:
        key = settings.serverchan_sendkey
        url = f"https://sctapi.ftqq.com/{key}.send"
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(url, data=serverchan_form(digest))
                response.raise_for_status()
                body = response.json()
        except Exception as exc:
            raise RuntimeError(_redact(str(exc), key)) from exc
        code = body.get("code") if isinstance(body, dict) else None
        if code not in (0, "0", None):
            message = body.get("message") if isinstance(body, dict) else body
            raise RuntimeError(f"Server酱返回错误：{message}")


class TelegramChannel:
    id = "telegram"
    label = "Telegram"

    def configured(self, settings: Settings) -> bool:
        return bool(settings.telegram_bot_token and settings.telegram_chat_id)

    async def send(self, digest: Digest, settings: Settings) -> None:
        token = settings.telegram_bot_token
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                for text in telegram_messages(digest):
                    response = await client.post(
                        url,
                        json={
                            "chat_id": settings.telegram_chat_id,
                            "text": text,
                            "parse_mode": "HTML",
                            "disable_web_page_preview": True,
                        },
                    )
                    body = response.json()
                    if response.status_code >= 400 or not body.get("ok", False):
                        description = body.get("description") if isinstance(body, dict) else response.text
                        raise RuntimeError(str(description or "Telegram 发送失败"))
        except Exception as exc:
            raise RuntimeError(_redact(str(exc), token)) from exc


class WeComChannel:
    id = "wecom"
    label = "企业微信"

    def configured(self, settings: Settings) -> bool:
        return bool(settings.wecom_webhook)

    async def send(self, digest: Digest, settings: Settings) -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(settings.wecom_webhook, json=wecom_body(digest))
            response.raise_for_status()
            body = response.json()
        if isinstance(body, dict) and body.get("errcode") not in (0, None):
            raise RuntimeError(str(body.get("errmsg") or "企业微信发送失败"))


class FeishuChannel:
    id = "feishu"
    label = "飞书"

    def configured(self, settings: Settings) -> bool:
        return bool(settings.feishu_webhook)

    async def send(self, digest: Digest, settings: Settings) -> None:
        payload = feishu_body(digest, settings.feishu_secret)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(settings.feishu_webhook, json=payload)
            response.raise_for_status()
            body = response.json()
        if isinstance(body, dict):
            code = body.get("code", body.get("StatusCode"))
            if code not in (0, None):
                raise RuntimeError(str(body.get("msg") or body.get("StatusMessage") or "飞书发送失败"))


CHANNELS: tuple[Channel, ...] = (
    EmailChannel(),
    ServerChanChannel(),
    TelegramChannel(),
    WeComChannel(),
    FeishuChannel(),
)


def _send_email(digest: Digest, settings: Settings) -> None:
    sender = settings.smtp_from or settings.smtp_user
    if not sender:
        raise RuntimeError("请设置 SMTP_FROM 或 SMTP_USER")
    recipients = [item.strip() for item in settings.smtp_to.split(",") if item.strip()]
    if not recipients:
        raise RuntimeError("请设置 SMTP_TO")
    message = EmailMessage()
    message["Subject"] = " ".join(digest.title.split())[:120]
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(render_plain(digest))
    message.add_alternative(render_html(digest), subtype="html")
    if settings.smtp_ssl:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
    try:
        if settings.smtp_tls and not settings.smtp_ssl:
            server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)
    finally:
        try:
            server.quit()
        except Exception:
            logger.debug("关闭 SMTP 连接失败", exc_info=True)


def _redact(text: str, secret: str) -> str:
    if secret:
        return text.replace(secret, "***")
    return text
