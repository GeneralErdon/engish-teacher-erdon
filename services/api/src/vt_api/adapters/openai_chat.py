"""Chat Completions protocol (official `openai` SDK): OpenAI, Gemini, Ollama, llama.cpp,
LM Studio and any other OpenAI-compatible server."""

from collections.abc import AsyncIterator, Sequence

import httpx2
import openai
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from vt_api.adapters.provider_errors import connection_failed, from_status, timed_out
from vt_api.domain.llm import ChatMessage, ProviderError

_GEMINI_MODEL_PREFIX = "models/"
"""Gemini's model list says `models/gemini-...`; chat requests take the bare id."""


def _to_openai(message: ChatMessage) -> ChatCompletionMessageParam:
    match message.role:
        case "system":
            return {"role": "system", "content": message.content}
        case "user":
            return {"role": "user", "content": message.content}
        case _:  # "assistant"
            return {"role": "assistant", "content": message.content}


def _provider_error(error: openai.APIError, base_url: str) -> ProviderError:
    match error:
        case openai.APIStatusError():
            return from_status(error.status_code, error.message)
        case openai.APITimeoutError():
            return timed_out(base_url)
        case _:
            return connection_failed(base_url)


class OpenAIChatModel:
    def __init__(self, client: openai.AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def _base_url(self) -> str:
        return str(self._client.base_url).rstrip("/")

    async def stream(
        self, messages: Sequence[ChatMessage], *, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        try:
            chunks = await self._client.chat.completions.create(
                model=self._model,
                messages=[_to_openai(message) for message in messages],
                max_tokens=openai.omit if max_tokens is None else max_tokens,
                stream=True,
            )
            async for chunk in chunks:
                for choice in chunk.choices:
                    if choice.delta.content:
                        yield choice.delta.content
        except openai.APIError as error:
            raise _provider_error(error, self._base_url) from error

    async def list_models(self) -> list[str]:
        try:
            ids = [model.id async for model in self._client.models.list()]
        except openai.APIError as error:
            raise _provider_error(error, self._base_url) from error
        return sorted({model_id.removeprefix(_GEMINI_MODEL_PREFIX) for model_id in ids})


class _OllamaModel(BaseModel):
    name: str


class _OllamaTags(BaseModel):
    models: list[_OllamaModel]


class OllamaChatModel(OpenAIChatModel):
    """Chats over Ollama's `/v1` Chat Completions; lists models with `/api/tags`, which works on
    both a local Ollama and ollama.com (whose `/v1/models` does not list the cloud models)."""

    def __init__(
        self, client: openai.AsyncOpenAI, model: str, *, http: httpx2.AsyncClient, root: str
    ) -> None:
        super().__init__(client, model)
        self._http = http
        self._root = root

    async def list_models(self) -> list[str]:
        headers = {"Authorization": f"Bearer {self._client.api_key}"}
        try:
            response = await self._http.get(f"{self._root}/api/tags", headers=headers)
        except httpx2.TimeoutException as error:
            raise timed_out(self._root) from error
        except httpx2.TransportError as error:
            raise connection_failed(self._root) from error
        if response.is_error:
            raise from_status(response.status_code, response.text)
        tags = _OllamaTags.model_validate_json(response.content)
        return sorted({model.name for model in tags.models})
