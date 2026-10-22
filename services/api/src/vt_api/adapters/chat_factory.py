"""Builds the `ChatModel` adapter for a provider's wire protocol."""

import anthropic
import httpx2
import openai

from vt_api.adapters.anthropic_chat import AnthropicChatModel
from vt_api.adapters.openai_chat import OllamaChatModel, OpenAIChatModel
from vt_api.domain.llm import ProviderConfig
from vt_api.ports.llm import ChatModel

NO_KEY = "none"
"""Sent when a provider needs no key. Never leave the SDKs without one: they would fall back
to `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` from the environment and send it to this server."""


class SdkChatModelFactory:
    """Owns the HTTP connection pools; one SDK client per call is cheap on top of them."""

    def __init__(
        self,
        *,
        openai_http: httpx2.AsyncClient,
        anthropic_http: httpx2.AsyncClient,
        timeout_s: float = 30.0,
        max_retries: int = 1,
    ) -> None:
        self._openai_http = openai_http
        self._anthropic_http = anthropic_http
        self._timeout_s = timeout_s
        self._max_retries = max_retries

    def __call__(self, provider: ProviderConfig) -> ChatModel:
        api_key = provider.api_key.get_secret_value() or NO_KEY
        match provider.protocol:
            case "anthropic":
                client = anthropic.AsyncAnthropic(
                    api_key=api_key,
                    base_url=provider.base_url,
                    http_client=self._anthropic_http,
                    timeout=self._timeout_s,
                    max_retries=self._max_retries,
                )
                return AnthropicChatModel(client, provider.model)
            case "ollama":
                # Ollama's root is documented without /v1; accept it either way.
                root = provider.base_url.removesuffix("/v1")
                return OllamaChatModel(
                    self._openai(api_key, f"{root}/v1"),
                    provider.model,
                    http=self._openai_http,
                    root=root,
                )
            case _:  # "openai"
                return OpenAIChatModel(self._openai(api_key, provider.base_url), provider.model)

    def _openai(self, api_key: str, base_url: str) -> openai.AsyncOpenAI:
        client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=self._openai_http,
            timeout=self._timeout_s,
            max_retries=self._max_retries,
        )
        # The SDK fills these from OPENAI_ORG_ID / OPENAI_PROJECT_ID; they belong to OpenAI only,
        # and the settings screen is the single source of what is sent.
        client.organization = None
        client.project = None
        return client

    async def aclose(self) -> None:
        await self._openai_http.aclose()
        await self._anthropic_http.aclose()
