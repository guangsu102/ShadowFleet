from __future__ import annotations

import time
import uuid
from collections import defaultdict
from threading import Lock
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


_RATE_LIMIT_STORAGE: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_LOCK = Lock()
RATE_LIMIT_MAX = 60
RATE_LIMIT_WINDOW = 60.0


def _clean_old_requests(client_ip: str, now: float) -> None:
    cutoff = now - RATE_LIMIT_WINDOW
    _RATE_LIMIT_STORAGE[client_ip] = [
        ts for ts in _RATE_LIMIT_STORAGE[client_ip] if ts > cutoff
    ]


def check_rate_limit(client_ip: str) -> bool:
    now = time.time()
    with _RATE_LIMIT_LOCK:
        _clean_old_requests(client_ip, now)
        if len(_RATE_LIMIT_STORAGE[client_ip]) >= RATE_LIMIT_MAX:
            return False
        _RATE_LIMIT_STORAGE[client_ip].append(now)
        return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        if not check_rate_limit(client_ip):
            return Response(
                content='{"error":"Rate limit exceeded","code":"RATE_LIMIT_EXCEEDED"}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(int(RATE_LIMIT_WINDOW))},
            )
        response = await call_next(request)
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        request.state.correlation_id = correlation_id
        start_time = time.perf_counter()

        logger = __import__("logging").getLogger("shadowfleet.api")
        logger.info(
            " --> %s %s [correlation_id=%s]",
            request.method,
            request.url.path,
            correlation_id,
        )

        response = await call_next(request)

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        if response.status_code == 422:
            try:
                body = await request.body()
                body_str = body.decode("utf-8", errors="replace")[:2000]
                logger.warning(
                    " <-- %s %s %d [%s] (%.2fms) body=%s",
                    request.method,
                    request.url.path,
                    response.status_code,
                    correlation_id,
                    elapsed_ms,
                    body_str,
                )
            except Exception:
                logger.info(
                    " <-- %s %s %d [%s] (%.2fms)",
                    request.method,
                    request.url.path,
                    response.status_code,
                    correlation_id,
                    elapsed_ms,
                )
        else:
            logger.info(
                " <-- %s %s %d [%s] (%.2fms)",
                request.method,
                request.url.path,
                response.status_code,
                correlation_id,
                elapsed_ms,
            )

        response.headers["X-Correlation-ID"] = correlation_id
        return response
