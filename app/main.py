"""ASGI entrypoint: build the FastAPI app, mount the API routers and serve the built UI."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.fixes import router as fixes_router
from app.api.leaderboard import router as leaderboard_router
from app.api.pages import router as pages_router
from app.api.scans import RateLimiter, router as scans_router
from app.config import settings
from app.jobs.scan_pipeline import Deps, fail_interrupted
from app.repo.db import engine as default_engine
from app.repo.db import init_db
from app.services.meta_llm import MetaLlm

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


def create_app(engine: Engine | None = None, deps: Deps | None = None) -> FastAPI:
    eng = engine or default_engine

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        init_db(eng)
        fail_interrupted(eng)
        if app.state.deps.llm_factory is MetaLlm and not settings.meta_api_key:
            logging.getLogger("uvicorn.error").error(
                "META_API_KEY is not set: scans are disabled until it is configured"
            )
        yield

    app = FastAPI(title="ax-scanner", lifespan=lifespan)
    app.state.engine = eng
    app.state.deps = deps or Deps()
    app.state.limiter = RateLimiter(settings.rate_limit_per_min)
    app.state.page_limiter = RateLimiter(120)  # page views of an existing scan: cheaper than a scan, still bounded

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "ERROR", "message": str(exc.detail)}
        return JSONResponse({"error": detail}, status_code=exc.status_code)

    @app.get("/health")
    def health() -> dict[str, bool | str]:
        llm_configured = not (app.state.deps.llm_factory is MetaLlm and not settings.meta_api_key)
        return {
            "ok": True,
            "ignore_robots_allowed": settings.allow_ignore_robots,
            "llm_model": settings.meta_model,
            "llm_configured": llm_configured,
        }

    app.include_router(scans_router)
    app.include_router(fixes_router)
    app.include_router(leaderboard_router)
    app.include_router(pages_router)

    dist = Path(__file__).resolve().parent.parent / "web" / "dist"
    if (dist / "index.html").exists():  # built UI: serve assets, fall back to index.html for client routes
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404, {"code": "NOT_FOUND", "message": "Not found"})
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
