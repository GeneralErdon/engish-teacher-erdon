from fastapi.testclient import TestClient

from vt_contracts.health import HealthResponse
from vt_pron import __version__
from vt_pron.app import create_app


def test_healthz() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert HealthResponse.model_validate_json(response.content) == HealthResponse(
        status="ok", service="pron", version=__version__
    )
