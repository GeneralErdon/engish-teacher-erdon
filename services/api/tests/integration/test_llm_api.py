"""`/v1/llm/*` end to end: real service, adapters and JSON store; providers faked at the HTTP
transport (`httpx2.MockTransport`)."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import create_autospec

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from vt_api.adapters.chat_factory import SdkChatModelFactory
from vt_api.adapters.json_llm_config import JsonLlmConfigRepository
from vt_api.adapters.openai_stt import OpenAISpeechToText
from vt_api.config import Settings
from vt_api.container import Container
from vt_api.domain.llm import environment_config
from vt_api.main import create_app
from vt_api.services.learner import LearnerService
from vt_api.services.llm import LlmService
from vt_contracts.llm import (
    ConnectionTestResult,
    LlmSettingsView,
    ModelList,
    ProblemDetail,
    ProviderInfo,
)

OLLAMA_CLOUD = {"kind": "ollama_cloud", "base_url": "https://ollama.com"}
FAKE_KEY = "fake" * 3 + "3456"  # built, not a literal: secret scanners flag key-like literals


def _ollama_cloud(request: httpx2.Request) -> httpx2.Response:
    """ollama.com: needs a key, lists models at /api/tags, chats over /v1."""
    if request.headers.get("authorization") != f"Bearer {FAKE_KEY}":
        return httpx2.Response(401, json={"error": "unauthorized"})
    if request.url.path == "/api/tags":
        return httpx2.Response(200, json={"models": [{"name": "gpt-oss:120b"}]})
    chunk = {
        "id": "c",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gpt-oss:120b",
        "choices": [{"index": 0, "delta": {"content": "Hello, learner!"}, "finish_reason": None}],
    }
    body = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"
    return httpx2.Response(200, text=body, headers={"content-type": "text/event-stream"})


@pytest.fixture
def chat_models() -> SdkChatModelFactory:
    transport = httpx2.MockTransport(_ollama_cloud)
    return SdkChatModelFactory(
        openai_http=httpx2.AsyncClient(transport=transport),
        anthropic_http=httpx2.AsyncClient(transport=transport),
        max_retries=0,
    )


@pytest.fixture
def container(
    tmp_path: Path, chat_models: SdkChatModelFactory, learner_service: LearnerService
) -> Container:
    environment = environment_config(
        kind="openai_compatible",
        base_url="http://llm:8080/v1",
        model="gemma-3-4b-it-q4",
        api_key=SecretStr(""),
    )
    return Container(
        llm=LlmService(
            repository=JsonLlmConfigRepository(tmp_path / "settings.json"),
            chat_models=chat_models,
            environment=environment,
        ),
        learner=learner_service,
        speech=create_autospec(OpenAISpeechToText, instance=True),
    )


@pytest.fixture
async def client(
    container: Container, chat_models: SdkChatModelFactory
) -> AsyncIterator[httpx2.AsyncClient]:
    app = create_app(Settings(_env_file=None), container=container)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    await chat_models.aclose()


async def test_providers(client: httpx2.AsyncClient) -> None:
    response = await client.get("/v1/llm/providers")

    assert response.status_code == 200
    kinds = [ProviderInfo.model_validate(p).kind for p in response.json()]
    assert kinds[:2] == ["ollama", "ollama_cloud"]


async def test_settings_start_from_the_environment(client: httpx2.AsyncClient) -> None:
    view = LlmSettingsView.model_validate_json((await client.get("/v1/llm/settings")).content)

    assert view.source == "environment"
    assert view.active == "openai_compatible"
    assert view.providers[0].model == "gemma-3-4b-it-q4"


async def test_configure_ollama_cloud_from_scratch(client: httpx2.AsyncClient) -> None:
    """The settings screen's flow: list models with the typed key, test, save, reuse the key."""
    with_key = {**OLLAMA_CLOUD, "api_key": FAKE_KEY}

    models = await client.post("/v1/llm/models", json=with_key)
    assert ModelList.model_validate_json(models.content).models == ["gpt-oss:120b"]

    test = await client.post("/v1/llm/test", json={**with_key, "model": "gpt-oss:120b"})
    result = ConnectionTestResult.model_validate_json(test.content)
    assert result.ok is True
    assert result.reply == "Hello, learner!"

    saved = await client.put("/v1/llm/settings", json={**with_key, "model": "gpt-oss:120b"})
    view = LlmSettingsView.model_validate_json(saved.content)
    assert view.active == "ollama_cloud"
    assert view.source == "saved"
    assert view.providers[0].api_key_hint == "…3456"
    assert FAKE_KEY not in saved.text

    # Later calls reuse the saved key without the UI ever seeing it again.
    again = await client.post("/v1/llm/models", json=OLLAMA_CLOUD)
    assert again.status_code == 200
    assert (await client.get("/v1/llm/settings")).json() == saved.json()


async def test_a_provider_that_needs_a_key_cannot_be_saved_without_one(
    client: httpx2.AsyncClient,
) -> None:
    response = await client.put("/v1/llm/settings", json={**OLLAMA_CLOUD, "model": "gpt-oss:120b"})

    assert response.status_code == 422
    assert ProblemDetail.model_validate_json(response.content).detail == (
        "Ollama Cloud needs an API key."
    )


async def test_reset_forgets_saved_settings(client: httpx2.AsyncClient) -> None:
    body = {**OLLAMA_CLOUD, "api_key": FAKE_KEY, "model": "gpt-oss:120b"}
    await client.put("/v1/llm/settings", json=body)

    view = LlmSettingsView.model_validate_json((await client.delete("/v1/llm/settings")).content)

    assert view.source == "environment"
    assert (await client.post("/v1/llm/models", json=OLLAMA_CLOUD)).status_code == 502


async def test_provider_failures(client: httpx2.AsyncClient) -> None:
    wrong_key = {**OLLAMA_CLOUD, "api_key": "wrong"}

    models = await client.post("/v1/llm/models", json=wrong_key)
    test = await client.post("/v1/llm/test", json={**wrong_key, "model": "gpt-oss:120b"})

    assert models.status_code == 502
    assert ProblemDetail.model_validate_json(models.content).detail == (
        "The provider rejected the API key (HTTP 401)."
    )
    assert test.status_code == 200
    assert ConnectionTestResult.model_validate_json(test.content).ok is False


async def test_invalid_bodies_are_rejected(client: httpx2.AsyncClient) -> None:
    response = await client.post("/v1/llm/models", json={"kind": "ollama", "base_url": "nope"})

    assert response.status_code == 422


def test_lifespan_keeps_an_injected_container(container: Container) -> None:
    app = create_app(Settings(_env_file=None), container=container)

    with TestClient(app) as client:
        assert client.get("/v1/llm/settings").status_code == 200
        assert app.state.container is container


def test_schema_documents_the_error_bodies() -> None:
    schema = create_app(Settings(_env_file=None)).openapi()

    models = schema["paths"]["/v1/llm/models"]["post"]["responses"]
    assert models["502"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ProblemDetail"
    }
