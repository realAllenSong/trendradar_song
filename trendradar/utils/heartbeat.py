# coding=utf-8
"""
Heartbeat helpers for long-running tasks.
"""

from __future__ import annotations

import os
import time
from typing import Optional

DEFAULT_HEARTBEAT_SECONDS = 60
ENV_HEARTBEAT_KEYS = (
    "TREND_RADAR_HEARTBEAT_SECONDS",
    "TRENRADAR_HEARTBEAT_SECONDS",
)


def _parse_positive_int(value: str) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def get_heartbeat_seconds(default: int = DEFAULT_HEARTBEAT_SECONDS) -> int:
    for key in ENV_HEARTBEAT_KEYS:
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        parsed = _parse_positive_int(raw)
        if parsed is not None:
            return parsed
    return default


class Heartbeat:
    """Rate-limited heartbeat logger."""

    def __init__(self, label: str, interval_seconds: Optional[int] = None) -> None:
        self.label = label
        self.interval_seconds = interval_seconds or get_heartbeat_seconds()
        self._last_emit = time.time()

    def maybe_emit(self, message: str) -> None:
        now = time.time()
        if now - self._last_emit >= self.interval_seconds:
            print(f"[heartbeat] {self.label}: {message}", flush=True)
            self._last_emit = now

    def force(self, message: str) -> None:
        print(f"[heartbeat] {self.label}: {message}", flush=True)
        self._last_emit = time.time()
