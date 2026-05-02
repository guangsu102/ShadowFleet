from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    TASK_CREATED = "task:created"
    TASK_STATUS_CHANGED = "task:status_changed"
    NODE_STATUS_CHANGED = "node:status_changed"
    SNAPSHOT_UPDATED = "snapshot:updated"


@dataclass
class SSEEvent:
    event_type: EventType
    data: dict[str, Any]
    correlation_id: str = ""

    def to_json(self) -> str:
        return json.dumps({
            "event_type": self.event_type.value,
            "correlation_id": self.correlation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": self.data,
        })

    def to_sse(self) -> str:
        return f"event: {self.event_type.value}\ndata: {self.to_json()}\n\n"


class EventBus:
    _instance: "EventBus | None" = None

    def __init__(self) -> None:
        if not hasattr(self, "_initialized"):
            self._queue: asyncio.Queue[SSEEvent] = asyncio.Queue(maxsize=1000)
            self._logger = logging.getLogger("shadowfleet.event_bus")
            self._initialized = True

    @classmethod
    def get_instance(cls) -> EventBus:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def publish(self, event: SSEEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._logger.warning("Event bus queue full, dropping event: %s", event.event_type)

    def subscribe(self) -> asyncio.Queue[SSEEvent]:
        return self._queue


_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus.get_instance()
    return _event_bus
