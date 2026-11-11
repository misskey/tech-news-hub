"""兼容 OpenAI Chat Completions 的客户端。密钥只放在环境变量里。"""

from __future__ import annotations

import json
import re

import httpx

SYSTEM_ITEMS = (
    "你是科技编辑，只根据给出的标题和摘录写简体中文。"
    "不要编造原文没有的功能、数字或发布时间。"
    "short 用一两句话说明这是什么，以及它像不像新工具、新发布或新趋势。"
    "long 用一段话补充背景，仍然只依据原文。"
    "takeaways 只列原文里出现的技术、编程语言或产品名，没有就给空数组。"
    "只返回 JSON 对象，形如 "
    '{"items":[{"index":0,"short":"...","long":"...","takeaways":["Rust"]}]}。'
)

SYSTEM_BRIEFING = (
    "你是科技编辑。根据给出的今日条目写一份一分钟能读完的简体中文简报。"
    "overview 用三四句话概括今天出现了哪些新工具、发布或主题，不要逐条念标题。"
    "highlights 是「今日新技术看点」，3 到 5 条，每条一句话，点明新东西是什么。"
    "不要编造输入里没有的产品或数字。只返回 JSON："
    '{"overview":"...","highlights":["..."]}'
)


class ChatClient:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 25):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def complete(self, messages: list[dict[str, str]]) -> str:
        url = f"{self.base_url}/chat/completions"
        try:
            response = httpx.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "temperature": 0.2, "messages": messages},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            return str(payload["choices"][0]["message"]["content"])
        except Exception as exc:
            raise RuntimeError(_redact(str(exc), self.api_key)) from exc


def parse_json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.I).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型没有返回 JSON")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("模型返回的不是 JSON 对象")
    return data


def _redact(text: str, secret: str) -> str:
    if secret:
        text = text.replace(secret, "***")
    return text[:300]
