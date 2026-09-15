from __future__ import annotations

import os
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
from api.router import assets, abandonment, config_api, dashboard, events, health, monitor, nodes, probes, tasks, xboard, utils
from api.auth.router import router as auth_router
from fastapi import APIRouter

health_router = APIRouter(tags=["health"])


@health_router.get("/api/v1/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runtime_context = get_runtime_context()
    AuthUserRepo.from_runtime_context(runtime_context).ensure_bootstrap_admin(
        os.environ.get("SHADOWFLEET_BOOTSTRAP_ADMIN_PASSWORD")
    )
    yield
    await lifespan_shutdown()

def _cors_allowed_origins() -> list[str]:
    raw_origins = os.environ.get("SHADOWFLEET_CORS_ALLOWED_ORIGINS", "")
    origins = list(
        dict.fromkeys(
            origin.strip() for origin in raw_origins.split(",") if origin.strip()
        )
    )
    if "*" in origins:
        raise RuntimeError(
            "SHADOWFLEET_CORS_ALLOWED_ORIGINS must list explicit origins"
        )
    return origins



def create_app() -> FastAPI:
    cors_allowed_origins = _cors_allowed_origins()
    app = FastAPI(
        title="ShadowFleet API",
        version="0.1.0",
        description="ShadowFleet EC2 Agent Node Management System — FastAPI Backend",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins,
        allow_credentials=bool(cors_allowed_origins),
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
    app.include_router(utils.router)
    app.include_router(health.router)
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
