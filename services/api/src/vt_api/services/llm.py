"""Use cases behind the `/v1/llm/*` API: read and save the provider settings, list a provider's
models, and test a connection."""

import asyncio
import time

from vt_api.domain.llm import (
    PROVIDERS,
    ChatMessage,
    LlmConfig,
    ProviderConfig,
    ProviderError,
    resolve_connection,
    to_view,
    with_provider,
)
from vt_api.ports.llm import ChatModel, ChatModelFactory, LlmConfigRepository
from vt_contracts.llm import (
    ConnectionTestRequest,
    ConnectionTestResult,
    LlmSettingsView,
    ProviderConnection,
    ProviderInfo,
    ProviderSettingsInput,
)

TEST_PROMPT = (ChatMessage("user", "Say hello to an English learner in one short sentence."),)
TEST_TIMEOUT_S = 60.0
"""Reasoning models can think for a while before the first word; past this, report a failure."""
MAX_REPLY_CHARS = 300


class LlmService:
    def __init__(
        self,
        *,
        repository: LlmConfigRepository,
        chat_models: ChatModelFactory,
        environment: LlmConfig,
    ) -> None:
        self._repository = repository
        self._chat_models = chat_models
        self._environment = environment

    @staticmethod
    def providers() -> list[ProviderInfo]:
        return list(PROVIDERS.values())

    async def config(self) -> LlmConfig:
        """Saved settings if there are any, else the environment's."""
        return await self._repository.load() or self._environment

    async def active_chat(self) -> tuple[ChatModel, ProviderConfig]:
        """The model the tutor talks with, and its settings."""
        provider = (await self.config()).active_provider
        return self._chat_models(provider), provider

    async def view(self) -> LlmSettingsView:
        return to_view(await self.config())

    async def save(self, update: ProviderSettingsInput) -> LlmSettingsView:
        """Save `update` and make it the active provider. Raises `InvalidSettingsError`."""
        config = with_provider(await self.config(), update)
        await self._repository.save(config)
        return to_view(config)

    async def reset(self) -> LlmSettingsView:
        """Forget everything saved from the UI, keys included: the environment applies again."""
        await self._repository.clear()
        return to_view(self._environment)

    async def list_models(self, connection: ProviderConnection) -> list[str]:
        """Raises `ProviderError`."""
        provider = resolve_connection(await self.config(), connection)
        return await self._chat_models(provider).list_models()

    async def test(self, request: ConnectionTestRequest) -> ConnectionTestResult:
        """Ask for a one-sentence reply and time it. Failures are results, not exceptions."""
        provider = resolve_connection(await self.config(), request, request.model)
        model = self._chat_models(provider)
        started = time.perf_counter()
        try:
            async with asyncio.timeout(TEST_TIMEOUT_S):
                reply = "".join([chunk async for chunk in model.stream(TEST_PROMPT)])
        except ProviderError as error:
            return ConnectionTestResult(ok=False, error=error.message)
        except TimeoutError:
            return ConnectionTestResult(
                ok=False, error=f"No complete reply within {TEST_TIMEOUT_S:.0f} s."
            )
        latency_ms = round((time.perf_counter() - started) * 1000)
        return ConnectionTestResult(
            ok=True, latency_ms=latency_ms, reply=reply.strip()[:MAX_REPLY_CHARS]
        )
