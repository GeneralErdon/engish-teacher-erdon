"""Application factory: `uvicorn --factory vt_pron.app:create_app`."""

from fastapi import FastAPI

from vt_contracts.health import HealthResponse
from vt_pron import __version__


def create_app() -> FastAPI:
    app = FastAPI(title="voice-tutor pron", version=__version__)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> HealthResponse:
        """Liveness only. Phase 2 also reports whether the phoneme model is loaded."""
        return HealthResponse(status="ok", service="pron", version=__version__)

    return app
