"""The chat adapters against canned provider responses (`httpx2.MockTransport`, no network)."""

import json
from collections.abc import AsyncIterator, Callable

import httpx2
import pytest
from pydantic import SecretStr

from vt_api.adapters.chat_factory import NO_KEY, SdkChatModelFactory
from vt_api.domain.llm import ChatMessage, ProviderConfig, ProviderError
from vt_contracts.llm import ProviderKind

type Handler = Callable[[httpx2.Request], httpx2.Response]

CONVERSATION = (
    ChatMessage("system", "You are an English teacher."),
    ChatMessage("user", "Hi!"),
    ChatMessage("assistant", "Hello! How are you?"),
    ChatMessage("user", "Fine, thanks."),
)


class Provider:
    """A fake provider: answers with `handler` and records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.handler: Handler = lambda _request: httpx2.Response(500)

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.handler(request)

    @property
    def last_json(self) -> dict[str, object]:
        body: dict[str, object] = json.loads(self.requests[-1].content)
        return body


@pytest.fixture
def provider() -> Provider:
    return Provider()


@pytest.fixture
async def factory(provider: Provider) -> AsyncIterator[SdkChatModelFactory]:
    transport = httpx2.MockTransport(provider)
    factory = SdkChatModelFactory(
        openai_http=httpx2.AsyncClient(transport=transport),
        anthropic_http=httpx2.AsyncClient(transport=transport),
        max_retries=0,
    )
    yield factory
    await factory.aclose()


def _config(kind: ProviderKind, base_url: str, key: str = "sk-test") -> ProviderConfig:
    return ProviderConfig(kind, base_url, "the-model", SecretStr(key))


def _sse(events: list[tuple[str | None, object]]) -> httpx2.Response:
    lines = []
    for event, data in events:
        if event:
            lines.append(f"event: {event}")
        lines.append(f"data: {data if isinstance(data, str) else json.dumps(data)}")
        lines.append("")
    body = "\n".join(lines) + "\n"
    return httpx2.Response(200, text=body, headers={"content-type": "text/event-stream"})


def _openai_chunk(delta: dict[str, str], finish: str | None = None) -> dict[str, object]:
    return {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "the-model",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


async def _collect(stream: AsyncIterator[str]) -> str:
    return "".join([chunk async for chunk in stream])


# ---------------------------------------------------------------- Chat Completions


async def test_openai_streams_text(factory: SdkChatModelFactory, provider: Provider) -> None:
    provider.handler = lambda _request: _sse(
        [
            (None, _openai_chunk({"role": "assistant", "content": "Great"})),
            (None, _openai_chunk({"content": " to hear!"})),
            (None, {**_openai_chunk({}, "stop"), "choices": []}),  # usage-only chunk
            (None, _openai_chunk({}, "stop")),
            (None, "[DONE]"),
        ]
    )
    model = factory(_config("openai", "https://api.openai.com/v1"))

    reply = await _collect(model.stream(CONVERSATION, max_tokens=50))

    assert reply == "Great to hear!"
    request = provider.requests[-1]
    assert str(request.url) == "https://api.openai.com/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-test"
    body = provider.last_json
    assert body["model"] == "the-model"
    assert body["max_tokens"] == 50
    assert [m["role"] for m in body["messages"]] == ["system", "user", "assistant", "user"]  # type: ignore[attr-defined]


async def test_openai_leaves_the_token_limit_to_the_provider(
    factory: SdkChatModelFactory, provider: Provider
) -> None:
    provider.handler = lambda _request: _sse([(None, "[DONE]")])

    await _collect(factory(_config("gemini", "https://g.example/openai")).stream(CONVERSATION))

    assert "max_tokens" not in provider.last_json


async def test_gemini_model_ids_lose_their_prefix(
    factory: SdkChatModelFactory, provider: Provider
) -> None:
    provider.handler = lambda _request: httpx2.Response(
        200,
        json={
            "object": "list",
            "data": [
                {"id": "models/gemini-3.8-flash", "object": "model", "created": 0, "owned_by": "g"},
                {"id": "gemini-3.8-flash", "object": "model", "created": 0, "owned_by": "g"},
                {"id": "embedding-001", "object": "model", "created": 0, "owned_by": "g"},
            ],
        },
    )

    models = await factory(_config("gemini", "https://g.example/openai")).list_models()

    assert models == ["embedding-001", "gemini-3.8-flash"]


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, "auth"),
        (403, "auth"),
        (404, "not_found"),
        (429, "rate_limited"),
        (400, "bad_request"),
        (503, "unavailable"),
    ],
)
async def test_openai_http_errors_become_provider_errors(
    factory: SdkChatModelFactory, provider: Provider, status: int, reason: str
) -> None:
    provider.handler = lambda _request: httpx2.Response(
        status, json={"error": {"message": "nope", "type": "x"}}
    )
    model = factory(_config("openai", "https://api.openai.com/v1"))

    with pytest.raises(ProviderError) as streaming:
        await _collect(model.stream(CONVERSATION))
    with pytest.raises(ProviderError) as listing:
        await model.list_models()

    assert streaming.value.reason == listing.value.reason == reason
    assert "sk-test" not in streaming.value.message


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (httpx2.ConnectError("refused"), "Could not connect to http://localhost:8080/v1."),
        (httpx2.ReadTimeout("slow"), "http://localhost:8080/v1 did not answer in time."),
    ],
)
async def test_openai_network_failures(
    factory: SdkChatModelFactory, provider: Provider, failure: Exception, message: str
) -> None:
    def fail(_request: httpx2.Request) -> httpx2.Response:
        raise failure

    provider.handler = fail
    model = factory(_config("openai_compatible", "http://localhost:8080/v1", key=""))

    with pytest.raises(ProviderError) as error:
        await _collect(model.stream(CONVERSATION))

    assert error.value.reason == "connection"
    assert error.value.message == message


async def test_never_falls_back_to_credentials_from_the_environment(
    factory: SdkChatModelFactory, provider: Provider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_ORG_ID", "org-env")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "proj-env")
    provider.handler = lambda _request: httpx2.Response(200, json={"object": "list", "data": []})

    await factory(_config("openai_compatible", "http://lmstudio:1234/v1", key="")).list_models()

    headers = provider.requests[-1].headers
    assert headers["authorization"] == f"Bearer {NO_KEY}"
    assert "openai-organization" not in headers
    assert "openai-project" not in headers


# ---------------------------------------------------------------- Ollama


@pytest.mark.parametrize("base_url", ["https://ollama.com", "https://ollama.com/v1"])
async def test_ollama_chats_under_v1_and_lists_tags(
    factory: SdkChatModelFactory, provider: Provider, base_url: str
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/tags":
            models = [{"name": "gpt-oss:120b", "size": 1}, {"name": "gemma4:31b", "size": 2}]
            return httpx2.Response(200, json={"models": models})
        return _sse([(None, _openai_chunk({"content": "Hi"})), (None, "[DONE]")])

    provider.handler = handler
    model = factory(_config("ollama_cloud", base_url))

    assert await model.list_models() == ["gemma4:31b", "gpt-oss:120b"]
    assert str(provider.requests[-1].url) == "https://ollama.com/api/tags"
    assert provider.requests[-1].headers["authorization"] == "Bearer sk-test"

    assert await _collect(model.stream(CONVERSATION)) == "Hi"
    assert str(provider.requests[-1].url) == "https://ollama.com/v1/chat/completions"


async def test_ollama_tag_errors(factory: SdkChatModelFactory, provider: Provider) -> None:
    provider.handler = lambda _request: httpx2.Response(401, text="unauthorized")

    with pytest.raises(ProviderError) as error:
        await factory(_config("ollama_cloud", "https://ollama.com")).list_models()

    assert error.value.reason == "auth"


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (httpx2.ConnectError("refused"), "Could not connect to http://localhost:11434."),
        (httpx2.ConnectTimeout("slow"), "http://localhost:11434 did not answer in time."),
    ],
)
async def test_ollama_tag_network_failures(
    factory: SdkChatModelFactory, provider: Provider, failure: Exception, message: str
) -> None:
    def fail(_request: httpx2.Request) -> httpx2.Response:
        raise failure

    provider.handler = fail

    with pytest.raises(ProviderError) as error:
        await factory(_config("ollama", "http://localhost:11434", key="")).list_models()

    assert error.value.message == message


# ---------------------------------------------------------------- Anthropic Messages

_MESSAGE_START = {
    "type": "message_start",
    "message": {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "content": [],
        "model": "the-model",
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 1},
    },
}


def _anthropic_reply() -> httpx2.Response:
    return _sse(
        [
            ("message_start", _MESSAGE_START),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "thinking", "thinking": "", "signature": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "thinking_delta", "thinking": "The learner is fine."},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "text_delta", "text": "Glad"},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "text_delta", "text": " to hear it."},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 1}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 12},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
    )


async def test_anthropic_streams_only_the_text(
    factory: SdkChatModelFactory, provider: Provider
) -> None:
    provider.handler = lambda _request: _anthropic_reply()

    reply = await _collect(
        factory(_config("anthropic", "https://api.anthropic.com")).stream(CONVERSATION)
    )

    assert reply == "Glad to hear it."
    request = provider.requests[-1]
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "sk-test"
    body = provider.last_json
    assert body["system"] == "You are an English teacher."
    assert body["max_tokens"] == 1024
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]  # type: ignore[attr-defined]


async def test_anthropic_without_a_system_prompt(
    factory: SdkChatModelFactory, provider: Provider
) -> None:
    provider.handler = lambda _request: _anthropic_reply()
    model = factory(_config("anthropic_compatible", "https://proxy.example/anthropic", key=""))

    await _collect(model.stream([ChatMessage("user", "Hi")], max_tokens=64))

    assert "system" not in provider.last_json
    assert provider.last_json["max_tokens"] == 64
    assert provider.requests[-1].headers["x-api-key"] == NO_KEY


async def test_anthropic_lists_models(factory: SdkChatModelFactory, provider: Provider) -> None:
    provider.handler = lambda _request: httpx2.Response(
        200,
        json={
            "data": [
                {
                    "id": model_id,
                    "type": "model",
                    "display_name": model_id,
                    "created_at": "2026-01-01T00:00:00Z",
                }
                for model_id in ("claude-sonnet-5-5", "claude-haiku-5-5")
            ],
            "has_more": False,
            "first_id": "claude-sonnet-5-5",
            "last_id": "claude-haiku-5-5",
        },
    )

    models = await factory(_config("anthropic", "https://api.anthropic.com")).list_models()

    assert models == ["claude-haiku-5-5", "claude-sonnet-5-5"]


@pytest.mark.parametrize(("status", "reason"), [(401, "auth"), (529, "unavailable")])
async def test_anthropic_http_errors(
    factory: SdkChatModelFactory, provider: Provider, status: int, reason: str
) -> None:
    provider.handler = lambda _request: httpx2.Response(
        status, json={"type": "error", "error": {"type": "x", "message": "nope"}}
    )
    model = factory(_config("anthropic", "https://api.anthropic.com"))

    with pytest.raises(ProviderError) as streaming:
        await _collect(model.stream(CONVERSATION))
    with pytest.raises(ProviderError) as listing:
        await model.list_models()

    assert streaming.value.reason == listing.value.reason == reason


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (httpx2.ConnectError("refused"), "Could not connect to https://api.anthropic.com."),
        (httpx2.ReadTimeout("slow"), "https://api.anthropic.com did not answer in time."),
    ],
)
async def test_anthropic_network_failures(
    factory: SdkChatModelFactory, provider: Provider, failure: Exception, message: str
) -> None:
    def fail(_request: httpx2.Request) -> httpx2.Response:
        raise failure

    provider.handler = fail

    with pytest.raises(ProviderError) as error:
        await factory(_config("anthropic", "https://api.anthropic.com")).list_models()

    assert error.value.message == message


async def test_closing_the_factory_closes_its_pools() -> None:
    openai_http, anthropic_http = httpx2.AsyncClient(), httpx2.AsyncClient()
    factory = SdkChatModelFactory(openai_http=openai_http, anthropic_http=anthropic_http)

    await factory.aclose()

    assert openai_http.is_closed
    assert anthropic_http.is_closed
