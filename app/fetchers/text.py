"""HTML 片段清洗和数字提取。"""

from __future__ import annotations

import html
import re


def clean_text(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_int(text: str) -> int:
    match = re.search(r"[\d,]+", text or "")
    if not match:
        return 0
    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return 0
