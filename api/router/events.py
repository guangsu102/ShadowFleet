from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.auth.dependencies import get_current_user
from api.deps import get_runtime_context
from database.sqlite_connection import SqliteConnectionManager
from services.runtime_service import RuntimeContext
from services.sse_event_repo import SSEEventRepo


router = APIRouter(prefix="/api/v1/events")

_pool = ThreadPoolExecutor(max_workers=2)


@router.get("/stream")
async def sse_stream(
    _current_user: Annotated[object, Depends(get_current_user)],
    ctx: RuntimeContext = Depends(get_runtime_context),
) -> StreamingResponse:
    db = SqliteConnectionManager(ctx)
    repo = SSEEventRepo.get_instance(db)
    logger = logging.getLogger("shadowfleet.sse")

    last_id = 0

    async def event_generator():
        nonlocal last_id
        try:
            while True:
                loop = asyncio.get_running_loop()
                events = await loop.run_in_executor(_pool, repo.poll_since, last_id, 15.0)
                if events:
                    for ev in events:
                        last_id = ev.id
                        yield f"id: {ev.id}\nevent: {ev.event_type}\ndata: {ev._raw_sse_json()}\n\n".encode("utf-8")
                else:
                    yield b": heartbeat\n\n"
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            logger.info("SSE client disconnected, last_event_id=%s", last_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def emit_sse_event(
    ctx: RuntimeContext,
    event_type: str,
    correlation_id: str,
    data: dict,
) -> int:
    db = SqliteConnectionManager(ctx)
    repo = SSEEventRepo.get_instance(db)
    return repo.write(event_type, correlation_id, data)
