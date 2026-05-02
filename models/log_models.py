from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LogContext:
    correlation_id: str
    event_type: str = "general"
