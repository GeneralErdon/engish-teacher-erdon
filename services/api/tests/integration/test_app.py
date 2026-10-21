from collections.abc import AsyncIterator
from pathlib import Path

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from vt_api import __version__
from vt_api.config import Settings
from vt_api.main import create_app
from vt_contracts.health import HealthResponse


def _client(settings: Settings) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app(settings))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with _client(Settings(_env_file=None)) as client:
        yield client


async def test_healthz(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert HealthResponse.model_validate_json(response.content) == HealthResponse(
        status="ok", service="api", version=__version__
    )


@pytest.mark.parametrize("origin", ["tauri://localhost", "http://tauri.localhost"])
async def test_cors_allows_the_desktop_app(client: httpx.AsyncClient, origin: str) -> None:
    response = await client.get("/healthz", headers={"Origin": origin})

    assert response.headers["access-control-allow-origin"] == origin


async def test_cors_rejects_other_origins(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz", headers={"Origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers


async def test_serves_the_ui_without_shadowing_the_api(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>voice-tutor</h1>")

    async with _client(Settings(_env_file=None, ui_dir=tmp_path)) as client:
        page = await client.get("/")
        health = await client.get("/healthz")

    assert page.text == "<h1>voice-tutor</h1>"
    assert health.status_code == 200


def test_lifespan_starts_and_stops_cleanly() -> None:
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/healthz").status_code == 200
