"""Speech-to-text against a fake Speaches (`httpx2.MockTransport`)."""

from collections.abc import AsyncIterator, Callable

import httpx2
import openai
import pytest

from vt_api.adapters.openai_stt import OpenAISpeechToText
from vt_api.domain.llm import ProviderError

MODEL = "Systran/faster-distil-whisper-small.en"
type Handler = Callable[[httpx2.Request], httpx2.Response]


class Speaches:
    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.handler: Handler = lambda _request: httpx2.Response(500)

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.handler(request)


@pytest.fixture
def speaches() -> Speaches:
    return Speaches()


@pytest.fixture
async def stt(speaches: Speaches) -> AsyncIterator[OpenAISpeechToText]:
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(speaches))
    client = openai.AsyncOpenAI(
        api_key="none", base_url="http://localhost:8000/v1", http_client=http, max_retries=0
    )
    yield OpenAISpeechToText(client)
    await http.aclose()


def _models(*ids: str) -> httpx2.Response:
    data = [{"id": i, "object": "model", "created": 0, "owned_by": "speaches"} for i in ids]
    return httpx2.Response(200, json={"object": "list", "data": data})


async def test_transcribes_english_wav(stt: OpenAISpeechToText, speaches: Speaches) -> None:
    speaches.handler = lambda _request: httpx2.Response(200, json={"text": " I went home. "})

    assert await stt.transcribe(b"RIFF....", MODEL, 30.0) == "I went home."

    request = speaches.requests[-1]
    assert str(request.url) == "http://localhost:8000/v1/audio/transcriptions"
    body = request.content
    assert MODEL.encode() in body
    assert b'name="language"\r\n\r\nen' in body
    assert b'filename="speech.wav"' in body


async def test_sends_the_per_call_timeout(stt: OpenAISpeechToText, speaches: Speaches) -> None:
    speaches.handler = lambda _request: httpx2.Response(200, json={"text": "Hi."})

    await stt.transcribe(b"RIFF....", MODEL, 47.0)

    timeout = speaches.requests[-1].extensions["timeout"]
    assert timeout["read"] == 47.0


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (lambda _r: httpx2.Response(404, json={"detail": "Model not found"}), "not_found"),
        (lambda _r: (_ for _ in ()).throw(httpx2.ConnectError("refused")), "connection"),
    ],
)
async def test_failures_become_provider_errors(
    stt: OpenAISpeechToText, speaches: Speaches, failure: Handler, reason: str
) -> None:
    speaches.handler = failure

    with pytest.raises(ProviderError) as error:
        await stt.transcribe(b"RIFF....", MODEL, 30.0)

    assert error.value.reason == reason


async def test_ready(stt: OpenAISpeechToText, speaches: Speaches) -> None:
    speaches.handler = lambda _request: _models("other", MODEL)

    status = await stt.status(MODEL)

    assert (status.reachable, status.model_ready, status.detail) == (True, True, None)
    assert status.base_url == "http://localhost:8000/v1"


async def test_model_not_downloaded(stt: OpenAISpeechToText, speaches: Speaches) -> None:
    speaches.handler = lambda _request: _models("other")

    status = await stt.status(MODEL)

    assert (status.reachable, status.model_ready) == (True, False)
    assert status.detail == f"The model {MODEL} is not downloaded."


async def test_server_down(stt: OpenAISpeechToText, speaches: Speaches) -> None:
    def refuse(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    speaches.handler = refuse

    status = await stt.status(MODEL)

    assert (status.reachable, status.model_ready) == (False, False)
    assert status.detail == "Could not connect to http://localhost:8000/v1."
