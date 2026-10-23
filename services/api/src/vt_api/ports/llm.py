"""Ports for chat models and for storing the provider settings."""

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from vt_api.domain.llm import ChatMessage, LlmConfig, ProviderConfig


class ChatModel(Protocol):
    """One provider + model. Every method raises `ProviderError` on failure."""

    def stream(
        self, messages: Sequence[ChatMessage], *, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        """The reply as text chunks, as the provider produces them.

        `max_tokens=None` leaves the limit to the provider where the protocol allows it.
        """
        ...

    async def list_models(self) -> list[str]:
        """Model ids the provider offers, sorted."""
        ...


class ChatModelFactory(Protocol):
    def __call__(self, provider: ProviderConfig) -> ChatModel: ...


class LlmConfigRepository(Protocol):
    """Settings saved from the UI. Keys are stored here, so the store must not be world-readable."""

    async def load(self) -> LlmConfig | None:
        """The saved settings, or `None` if nothing usable is saved."""
        ...

    async def save(self, config: LlmConfig) -> None: ...

    async def clear(self) -> None: ...
