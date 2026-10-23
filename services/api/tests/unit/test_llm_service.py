import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

import pytest
from pydantic import SecretStr

from vt_api.domain.llm import (
    PROVIDERS,
    ChatMessage,
    InvalidSettingsError,
    LlmConfig,
    ProviderConfig,
    ProviderError,
    environment_config,
)
from vt_api.ports.llm import ChatModel
from vt_api.services import llm as llm_service
from vt_api.services.llm import LlmService
from vt_contracts.llm import ConnectionTestRequest, ProviderConnection, ProviderSettingsInput

ENVIRONMENT = environment_config(
    kind="openai_compatible", base_url="http://llm:8080/v1", model="gemma", api_key=SecretStr("")
)


class MemoryRepository:
    def __init__(self) -> None:
        self.saved: LlmConfig | None = None

    async def load(self) -> LlmConfig | None:
        return self.saved

    async def save(self, config: LlmConfig) -> None:
        self.saved = config

    async def clear(self) -> None:
        self.saved = None


@dataclass
class ScriptedModel:
    chunks: Sequence[str] = ("Hello", " there! ")
    error: ProviderError | None = None
    delay_s: float = 0.0
    models: Sequence[str] = ("b", "a")

    async def stream(
        self, messages: Sequence[ChatMessage], *, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        await asyncio.sleep(self.delay_s)
        if self.error:
            raise self.error
        for chunk in self.chunks:
            yield chunk

    async def list_models(self) -> list[str]:
        if self.error:
            raise self.error
        return sorted(self.models)


@dataclass
class ScriptedFactory:
    model: ScriptedModel = field(default_factory=ScriptedModel)
    calls: list[ProviderConfig] = field(default_factory=list)

    def __call__(self, provider: ProviderConfig) -> ChatModel:
        self.calls.append(provider)
        return self.model


@pytest.fixture
def repository() -> MemoryRepository:
    return MemoryRepository()


@pytest.fixture
def factory() -> ScriptedFactory:
    return ScriptedFactory()


@pytest.fixture
def service(repository: MemoryRepository, factory: ScriptedFactory) -> LlmService:
    return LlmService(repository=repository, chat_models=factory, environment=ENVIRONMENT)


def test_lists_the_catalogue() -> None:
    assert [p.kind for p in LlmService.providers()] == list(PROVIDERS)


async def test_environment_applies_until_something_is_saved(service: LlmService) -> None:
    view = await service.view()

    assert view.source == "environment"
    assert view.active == "openai_compatible"


async def test_save_then_reset(service: LlmService, repository: MemoryRepository) -> None:
    update = ProviderSettingsInput(
        kind="ollama_cloud", base_url="https://ollama.com", model="gpt-oss:120b", api_key="k"
    )

    saved = await service.save(update)

    assert saved.active == "ollama_cloud"
    assert repository.saved is not None
    assert (await service.view()).source == "saved"

    reset = await service.reset()

    assert reset.source == "environment"
    assert repository.saved is None


async def test_save_rejects_incomplete_settings(service: LlmService) -> None:
    update = ProviderSettingsInput(kind="openai", base_url="https://api.openai.com/v1", model="m")

    with pytest.raises(InvalidSettingsError):
        await service.save(update)


async def test_lists_models_with_the_saved_key(
    service: LlmService, factory: ScriptedFactory
) -> None:
    await service.save(
        ProviderSettingsInput(
            kind="anthropic", base_url="https://api.anthropic.com", model="m", api_key="secret"
        )
    )

    models = await service.list_models(
        ProviderConnection(kind="anthropic", base_url="https://api.anthropic.com")
    )

    assert models == ["a", "b"]
    assert factory.calls[-1].api_key.get_secret_value() == "secret"


async def test_connection_test_reports_the_reply_and_latency(
    service: LlmService, factory: ScriptedFactory
) -> None:
    request = ConnectionTestRequest(kind="ollama", base_url="http://localhost:11434", model="g")

    result = await service.test(request)

    assert result.ok is True
    assert result.reply == "Hello there!"
    assert result.latency_ms is not None
    assert factory.calls[-1].model == "g"


async def test_connection_test_reports_provider_errors(
    service: LlmService, factory: ScriptedFactory
) -> None:
    factory.model.error = ProviderError("auth", "The provider rejected the API key (HTTP 401).")
    request = ConnectionTestRequest(kind="openai", base_url="https://api.openai.com/v1", model="m")

    result = await service.test(request)

    assert result.ok is False
    assert result.error == "The provider rejected the API key (HTTP 401)."


async def test_connection_test_gives_up_on_slow_models(
    service: LlmService, factory: ScriptedFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_service, "TEST_TIMEOUT_S", 0.01)
    factory.model.delay_s = 1.0
    request = ConnectionTestRequest(kind="openai", base_url="https://api.openai.com/v1", model="m")

    result = await service.test(request)

    assert result.ok is False
    assert result.error is not None
    assert "No complete reply" in result.error
