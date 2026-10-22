"""Messages protocol (official `anthropic` SDK): Anthropic and Anthropic-compatible servers."""

from collections.abc import AsyncIterator, Sequence

import anthropic
from anthropic.types import MessageParam

from vt_api.adapters.provider_errors import connection_failed, from_status, timed_out
from vt_api.domain.llm import ChatMessage, ProviderError

DEFAULT_MAX_TOKENS = 1024
"""The Messages API requires a limit. Thinking counts towards it, so keep some headroom."""


def _provider_error(error: anthropic.APIError, base_url: str) -> ProviderError:
    match error:
        case anthropic.APIStatusError():
            return from_status(error.status_code, error.message)
        case anthropic.APITimeoutError():
            return timed_out(base_url)
        case _:
            return connection_failed(base_url)


class AnthropicChatModel:
    def __init__(self, client: anthropic.AsyncAnthropic, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def _base_url(self) -> str:
        return str(self._client.base_url).rstrip("/")

    async def stream(
        self, messages: Sequence[ChatMessage], *, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        # System prompts are a request parameter here, not a message.
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        turns: list[MessageParam] = [
            {"role": m.role, "content": m.content} for m in messages if m.role != "system"
        ]
        try:
            events = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
                system=system or anthropic.omit,
                messages=turns,
                stream=True,
            )
            async for event in events:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield event.delta.text
        except anthropic.APIError as error:
            raise _provider_error(error, self._base_url) from error

    async def list_models(self) -> list[str]:
        try:
            return sorted([model.id async for model in self._client.models.list()])
        except anthropic.APIError as error:
            raise _provider_error(error, self._base_url) from error
