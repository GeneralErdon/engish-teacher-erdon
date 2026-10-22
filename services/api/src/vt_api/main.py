"""Application factory: `uvicorn --factory vt_api.main:create_app`."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from vt_api import __version__
from vt_api.config import Settings
from vt_api.container import Container, build_container
from vt_api.http import health, learner, llm, speech, ws
from vt_api.http.schema import openapi_with_events


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    """`container` replaces the production wiring (tests pass one built from fakes)."""
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            if container is None:
                app.state.container = await stack.enter_async_context(build_container(settings))
            yield

    app = FastAPI(title="voice-tutor api", version=__version__, lifespan=lifespan)
    app.state.allowed_origins = frozenset(settings.cors_origins)
    if container is not None:
        app.state.container = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.include_router(health.router)
    app.include_router(llm.router)
    app.include_router(learner.router)
    app.include_router(speech.router)
    app.include_router(ws.router)

    app.openapi = lambda: openapi_with_events(app)  # type: ignore[method-assign]

    # Browser / home-lab mode: the same UI the desktop app bundles. Mounted last so API routes win.
    if settings.ui_dir is not None:
        app.mount("/", StaticFiles(directory=settings.ui_dir, html=True), name="ui")

    return app
