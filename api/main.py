from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from api.deps import get_runtime_context, lifespan_shutdown
from api.auth.db import AuthUserRepo
from api.exceptions.handlers import register_exception_handlers
from api.middleware import RateLimitMiddleware, RequestLoggingMiddleware
from api.router import assets, abandonment, config_api, dashboard, events, monitor, nodes, probes, tasks, xboard
from api.auth.router import router as auth_router
from fastapi import APIRouter

health_router = APIRouter(tags=["health"])


@health_router.get("/api/v1/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_runtime_context()
    AuthUserRepo().ensure_default_admin()
    yield
    await lifespan_shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="ShadowFleet API",
        version="0.1.0",
        description="ShadowFleet EC2 Agent Node Management System — FastAPI Backend",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    app.include_router(auth_router)
    app.include_router(dashboard.router)
    app.include_router(assets.router)
    app.include_router(nodes.router)
    app.include_router(tasks.router)
    app.include_router(probes.router)
    app.include_router(monitor.router)
    app.include_router(config_api.router)
    app.include_router(abandonment.router)
    app.include_router(xboard.router)
    app.include_router(events.router)
    app.include_router(health_router)

    register_exception_handlers(app)

    # Vue SPA 静态文件（由 frontend builder 或 host 目录提供）
    frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
