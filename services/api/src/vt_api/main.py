"""Application factory: `uvicorn --factory vt_api.main:create_app`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from vt_api import __version__
from vt_api.config import Settings
from vt_api.http import health


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Phase 1: build the container (ports -> adapters) and check every dependency here.
        yield

    app = FastAPI(title="voice-tutor api", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.include_router(health.router)

    # Browser / home-lab mode: the same UI the desktop app bundles. Mounted last so API routes win.
    if settings.ui_dir is not None:
        app.mount("/", StaticFiles(directory=settings.ui_dir, html=True), name="ui")

    return app
