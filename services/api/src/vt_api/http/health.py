from fastapi import APIRouter

from vt_api import __version__
from vt_contracts.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> HealthResponse:
    """Liveness only. Readiness (every model endpoint reachable) arrives with the container."""
    return HealthResponse(status="ok", service="api", version=__version__)
