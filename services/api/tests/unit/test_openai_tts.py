"""Text-to-speech against a fake Speaches (`httpx2.MockTransport`)."""

import json
from collections.abc import AsyncIterator, Callable

import httpx2
import openai
import pytest

from vt_api.adapters.openai_tts import OpenAITextToSpeech
from vt_api.domain.llm import ProviderError
from vt_api.domain.speech import VoiceChoice

MODEL = "speaches-ai/Kokoro-82M-v1.0-ONNX"
KOKORO = VoiceChoice(MODEL, "af_heart", 0.95)
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
async def tts(speaches: Speaches) -> AsyncIterator[OpenAITextToSpeech]:
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(speaches))
    client = openai.AsyncOpenAI(
        api_key="none", base_url="http://localhost:8000/v1", http_client=http, max_retries=0
    )
    yield OpenAITextToSpeech(client)
    await http.aclose()


def _streamed(*chunks: bytes) -> httpx2.Response:
    async def body() -> AsyncIterator[bytes]:
        for chunk in chunks:
            yield chunk

    return httpx2.Response(200, content=body(), headers={"content-type": "audio/pcm"})


async def _speak(
    tts: OpenAITextToSpeech, text: str = "Nice!", voice: VoiceChoice = KOKORO
) -> list[bytes]:
    return [chunk async for chunk in tts.synthesize(text, voice)]


async def test_streams_raw_pcm_from_kokoro(tts: OpenAITextToSpeech, speaches: Speaches) -> None:
    speaches.handler = lambda _request: _streamed(b"\x01\x00\x02\x00", b"\x03\x00")

    assert await _speak(tts) == [b"\x01\x00\x02\x00", b"\x03\x00"]

    request = speaches.requests[-1]
    assert str(request.url) == "http://localhost:8000/v1/audio/speech"
    assert json.loads(request.content) == {
        "model": MODEL,
        "voice": "af_heart",
        "input": "Nice!",
        "response_format": "pcm",
        "speed": 0.95,
    }


async def test_piper_asks_for_24k(tts: OpenAITextToSpeech, speaches: Speaches) -> None:
    speaches.handler = lambda _request: _streamed(b"\x01\x00")
    piper = VoiceChoice("speaches-ai/piper-en_US-lessac-medium", "lessac", 1.0, 24000)

    await _speak(tts, voice=piper)
    await _speak(tts)

    with_rate, without_rate = (json.loads(r.content) for r in speaches.requests)
    assert with_rate["sample_rate"] == 24000
    assert "sample_rate" not in without_rate


async def test_never_splits_a_sample(tts: OpenAITextToSpeech, speaches: Speaches) -> None:
    speaches.handler = lambda _request: _streamed(b"\x01", b"\x00\x02", b"\x00\x03\x00")

    chunks = await _speak(tts)

    assert chunks == [b"\x01\x00", b"\x02\x00\x03\x00"]


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (lambda _r: httpx2.Response(404, json={"detail": "Model not found"}), "not_found"),
        (lambda _r: (_ for _ in ()).throw(httpx2.ConnectError("refused")), "connection"),
    ],
)
async def test_failures_become_provider_errors(
    tts: OpenAITextToSpeech, speaches: Speaches, failure: Handler, reason: str
) -> None:
    speaches.handler = failure

    with pytest.raises(ProviderError) as error:
        await _speak(tts)

    assert error.value.reason == reason


async def test_status(tts: OpenAITextToSpeech, speaches: Speaches) -> None:
    model = {"id": MODEL, "object": "model", "created": 0, "owned_by": "speaches"}
    speaches.handler = lambda _request: httpx2.Response(
        200, json={"object": "list", "data": [model]}
    )

    status = await tts.status(MODEL)

    assert (status.model, status.model_ready) == (MODEL, True)
