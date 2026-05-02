from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from database.sqlite_connection import SqliteConnectionManager

if False:
    pass


@dataclass
class SSEStoredEvent:
    id: int
    event_type: str
    correlation_id: str
    payload: dict[str, Any]
    created_at: str

    def to_sse_line(self) -> str:
        data = {
            "event_type": self.event_type,
            "correlation_id": self.correlation_id,
            "timestamp": self.created_at,
            "data": self.payload,
            "event_id": self.id,
        }
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _raw_sse_json(self) -> str:
        return json.dumps({
            "event_type": self.event_type,
            "correlation_id": self.correlation_id,
            "timestamp": self.created_at,
            "data": self.payload,
            "event_id": self.id,
        }, ensure_ascii=False)


class SSEEventRepo:
    _instance: SSEEventRepo | None = None

    def __init__(self, db: SqliteConnectionManager) -> None:
        self._db = db
        self._logger = logging.getLogger("shadowfleet.sse_event_repo")
        self._last_poll_time: float = 0.0

    @classmethod
    def get_instance(cls, db: SqliteConnectionManager) -> SSEEventRepo:
        if cls._instance is None:
            cls._instance = cls(db)
        return cls._instance

    def write(self, event_type: str, correlation_id: str, payload: dict[str, Any]) -> int:
        sql = """
            INSERT INTO sse_events (event_type, correlation_id, payload_json, created_at)
            VALUES (?, ?, ?, ?)
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._db.connection() as conn:
            cursor = conn.execute(sql, (event_type, correlation_id, json.dumps(payload, ensure_ascii=False), now))
            conn.commit()
            self._logger.debug("SSE event written: type=%s id=%s", event_type, cursor.lastrowid)
            return int(cursor.lastrowid)

    def poll_since(self, since_id: int, timeout_seconds: float = 30.0) -> list[SSEStoredEvent]:
        start = time.monotonic()
        poll_interval = 0.5

        while True:
            with self._db.connection() as conn:
                rows = conn.execute(
                    "SELECT id, event_type, correlation_id, payload_json, created_at "
                    "FROM sse_events WHERE id > ? ORDER BY id ASC LIMIT 100",
                    (since_id,),
                ).fetchall()
            if rows:
                return [
                    SSEStoredEvent(
                        id=int(r["id"]),
                        event_type=str(r["event_type"]),
                        correlation_id=str(r["correlation_id"]) if r["correlation_id"] else "",
                        payload=json.loads(str(r["payload_json"])),
                        created_at=str(r["created_at"]),
                    )
                    for r in rows
                ]

            elapsed = time.monotonic() - start
            if elapsed >= timeout_seconds:
                return []

            time.sleep(poll_interval)
