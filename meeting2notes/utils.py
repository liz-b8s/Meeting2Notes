"""
Small utility functions.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
import sys


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


def send_notification(title: str, message: str = "", sound: bool = True) -> None:
    """Send a macOS notification. Fails silently on other platforms."""
    if sys.platform != "darwin":
        return

    script = f'display notification "{message}" with title "{title}"'
    if sound:
        script += ' sound name "Glass"'

    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass  # osascript not available
