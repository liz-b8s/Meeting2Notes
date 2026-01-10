"""
Small utility functions.
"""

from __future__ import annotations

import datetime as dt
import re


def iso_timestamp_local() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def safe_filename(name: str, max_len: int = 120) -> str:
    name = re.sub(r"[\/\\:\*\?\"<>\|]+", "-", name.strip())
    name = re.sub(r"\s+", " ", name).strip()
    return (name[:max_len].rstrip() or "Untitled")


def markdown_to_text(md: str) -> str:
    text = md
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"- \[ \]\s*", "- ", text)
    text = re.sub(r"^-{3,}$", "", text, flags=re.MULTILINE)
    return text.strip()
