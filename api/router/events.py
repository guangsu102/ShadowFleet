from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt

from api.auth.jwt import ALGORITHM as _ALGORITHM, _get_secret as _jwt_secret_loader
from api.deps import get_runtime_context
from database.sqlite_connection import SqliteConnectionManager
from services.runtime_service import RuntimeContext
from services.sse_event_repo import SSEEventRepo


router = APIRouter(prefix="/api/v1/events")

_pool = ThreadPoolExecutor(max_workers=2)


def _build_sse(event_type: str, data: dict) -> bytes:
    payload = json.dumps(data)
    return f"event: {event_type}\ndata: {payload}\n\n".encode("utf-8")


def _validate_token(request: Request) -> int:
    """
    Validate the JWT token from the `token` query parameter.
    EventSource cannot send custom HTTP headers, so the token is passed via query string.
    Returns the user_id on success, raises HTTPException on failure.
    """
    from fastapi import HTTPException, status

    token = request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    try:
        payload = jwt.decode(token, _jwt_secret_loader(), algorithms=[_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject")

    from api.auth.db import AuthUserRepo
    user = AuthUserRepo().get_by_id(int(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return int(user_id)


@router.get("/stream")
async def sse_stream(
    request: Request,
    ctx: RuntimeContext = Depends(get_runtime_context),
) -> StreamingResponse:
    """
    SSE endpoint for real-time events.

    Authentication: EventSource cannot set custom HTTP headers, so the JWT
    access token must be passed as the `token` query parameter:
        new EventSource('/api/v1/events/stream?token=' + encodeURIComponent(accessToken))

    If authentication fails, an SSE-formatted auth error event is sent and the
    connection is closed. This allows the client to detect the error via onmessage
    and redirect to login without triggering an infinite reconnect loop.
    """
    # Authenticate before starting the stream; on failure, send SSE error then close.
    try:
        user_id = _validate_token(request)
    except Exception as e:
        # Return a streaming response that yields an auth error then closes.
        async def auth_error_generator():
            yield _build_sse("auth:error", {"error": str(e), "type": "auth_error"})
            yield _build_sse("close", {})

        return StreamingResponse(
            auth_error_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "close",
                "X-Accel-Buffering": "no",
            },
        )

    logger = logging.getLogger("shadowfleet.sse")
    db = SqliteConnectionManager(ctx)
    repo = SSEEventRepo.get_instance(db)

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
            logger.info("SSE client disconnected (user_id=%s, last_event_id=%s)", user_id, last_id)

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
