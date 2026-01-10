"""
Timing and debug helpers extracted from the original script.

This module provides simple timestamped status logging and a
context manager for timing steps. It's intentionally lightweight so
it can be used without pulling in the rest of the package.
"""

from __future__ import annotations

import datetime as dt
import time
from contextlib import contextmanager

DEBUG_TIMING: bool = False
START_TS: float = time.perf_counter()


def _now_str() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")


def _elapsed() -> str:
    return f"{time.perf_counter() - START_TS:.1f}s"


def status(msg: str) -> None:
    """Timestamped status messages (debug only)."""
    if not DEBUG_TIMING:
        return
    print(f"[{_now_str()} +{_elapsed():>6}] {msg}", flush=True)


@contextmanager
def step(msg: str):
    """Timed step context manager (debug only)."""
    if not DEBUG_TIMING:
        yield
        return
    t0 = time.perf_counter()
    status(f"{msg} …")
    try:
        yield
    finally:
        dt_s = time.perf_counter() - t0
        status(f"{msg} ✓ ({dt_s:.1f}s)")
