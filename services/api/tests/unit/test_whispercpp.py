"""The whisper.cpp adapter against a fake server (`httpx2.MockTransport`)."""

import asyncio
from collections.abc import AsyncIterator, Callable

import httpx2
import pytest

from vt_api.adapters.whispercpp import CONNECT_TIMEOUT_S, WhisperCppSpeechToText
from vt_api.domain.llm import ProviderError
from vt_api.domain.speech import EngineUnreachable

BASE = "http://gpu:8080/v1"
MODEL_A = "models--g--w/snapshots/r/a.bin"
MODEL_B = "models--g--w/snapshots/r/b.bin"
type Handler = Callable[[httpx2.Request], httpx2.Response]


def _ok(request: httpx2.Request) -> httpx2.Response:
    if request.url.path.endswith("/load"):
        return httpx2.Response(200, text="Load was successful!")
    return httpx2.Response(200, json={"text": " Hello there.\n"})


class Fake:
    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.handler: Handler = _ok
        self.delay_s = 0.0
        self.active = 0
        self.max_active = 0

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay_s)
            return self.handler(request)
        finally:
            self.active -= 1

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


def _raising(error: Exception) -> Handler:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error

    return handler


@pytest.fixture
def fake() -> Fake:
    return Fake()


@pytest.fixture
async def stt(fake: Fake) -> AsyncIterator[WhisperCppSpeechToText]:
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(fake))
    yield WhisperCppSpeechToText(http, BASE, "/models/")
    await http.aclose()


def _request() -> httpx2.Request:
    return httpx2.Request("GET", BASE)


async def test_transcribe_posts_the_wav_and_strips_the_text(
    fake: Fake, stt: WhisperCppSpeechToText
) -> None:
    assert await stt.transcribe(b"RIFFdata", MODEL_A, 30) == "Hello there."

    request = fake.requests[-1]
    assert str(request.url) == "http://gpu:8080/v1/audio/transcriptions"
    body = request.content
    assert b'name="file"; filename="speech.wav"' in body
    assert b"RIFFdata" in body
    assert b'name="response_format"' in body
    assert b'name="language"' in body
    assert b"json" in body
    assert b"en" in body


async def test_transcribe_loads_a_different_model_first(
    fake: Fake, stt: WhisperCppSpeechToText
) -> None:
    await stt.transcribe(b"w", MODEL_A, 30)
    assert fake.paths() == ["/v1/load", "/v1/audio/transcriptions"]
    assert b"/models/models--g--w/snapshots/r/a.bin" in fake.requests[0].content
    assert b'name="model"' in fake.requests[0].content

    await stt.transcribe(b"w", MODEL_A, 30)
    assert fake.paths() == ["/v1/load", "/v1/audio/transcriptions", "/v1/audio/transcriptions"]

    await stt.transcribe(b"w", MODEL_B, 30)
    assert fake.paths()[3:] == ["/v1/load", "/v1/audio/transcriptions"]
    assert b"/models/models--g--w/snapshots/r/b.bin" in fake.requests[3].content


async def test_load_always_asks_the_server(fake: Fake, stt: WhisperCppSpeechToText) -> None:
    """No route says which model the server holds, and it may have restarted with its startup
    model since: a conversation start always loads."""
    await stt.load(MODEL_A)
    await stt.load(MODEL_A)

    assert fake.paths() == ["/v1/load", "/v1/load"]
    assert all(b"/models/models--g--w/snapshots/r/a.bin" in r.content for r in fake.requests)


async def test_transcribe_right_after_load_does_not_load_again(
    fake: Fake, stt: WhisperCppSpeechToText
) -> None:
    await stt.load(MODEL_A)
    await stt.transcribe(b"w", MODEL_A, 30)

    assert fake.paths() == ["/v1/load", "/v1/audio/transcriptions"]


async def test_a_load_waits_for_a_transcription_and_its_load(
    fake: Fake, stt: WhisperCppSpeechToText
) -> None:
    fake.delay_s = 0.01

    await asyncio.gather(stt.transcribe(b"w", MODEL_A, 30), stt.load(MODEL_B))

    assert fake.paths() == ["/v1/load", "/v1/audio/transcriptions", "/v1/load"]
    assert b"/models/models--g--w/snapshots/r/a.bin" in fake.requests[0].content
    assert b"/models/models--g--w/snapshots/r/b.bin" in fake.requests[2].content
    assert fake.max_active == 1


async def test_concurrent_loads_are_serialised(fake: Fake, stt: WhisperCppSpeechToText) -> None:
    fake.delay_s = 0.01

    await asyncio.gather(stt.load(MODEL_A), stt.load(MODEL_B))

    assert fake.paths() == ["/v1/load", "/v1/load"]
    assert fake.max_active == 1


async def test_failed_load_forgets_the_loaded_model(
    fake: Fake, stt: WhisperCppSpeechToText
) -> None:
    await stt.load(MODEL_A)
    fake.handler = lambda _r: httpx2.Response(400, json={"error": "model not found!"})
    with pytest.raises(ProviderError, match="model not found!") as refused:
        await stt.load(MODEL_B)
    assert not isinstance(refused.value, EngineUnreachable)

    fake.handler = _ok
    await stt.transcribe(b"w", MODEL_A, 30)  # forgotten: loaded again
    assert fake.paths() == ["/v1/load"] * 3 + ["/v1/audio/transcriptions"]

    fake.handler = _raising(httpx2.RemoteProtocolError("dropped", request=_request()))
    with pytest.raises(ProviderError) as dropped:
        await stt.load(MODEL_B)
    assert not isinstance(dropped.value, EngineUnreachable)

    fake.handler = _ok
    await stt.transcribe(b"w", MODEL_A, 30)  # forgotten: loaded again
    assert fake.paths()[4:] == ["/v1/load", "/v1/load", "/v1/audio/transcriptions"]


@pytest.mark.parametrize("error_type", [httpx2.ConnectError, httpx2.ConnectTimeout])
async def test_connection_refused_is_engine_unreachable(
    fake: Fake,
    stt: WhisperCppSpeechToText,
    error_type: type[httpx2.ConnectError] | type[httpx2.ConnectTimeout],
) -> None:
    fake.handler = _raising(error_type("refused", request=_request()))

    with pytest.raises(EngineUnreachable) as on_load:
        await stt.load(MODEL_A)
    assert on_load.value.reason == "connection"
    assert str(on_load.value) == f"Could not connect to {BASE}."

    with pytest.raises(EngineUnreachable):
        await stt.transcribe(b"w", MODEL_A, 30)


async def test_unreachable_forgets_the_loaded_model(
    fake: Fake, stt: WhisperCppSpeechToText
) -> None:
    await stt.load(MODEL_A)
    fake.handler = _raising(httpx2.ConnectError("refused", request=_request()))
    with pytest.raises(EngineUnreachable):
        await stt.transcribe(b"w", MODEL_A, 30)

    fake.handler = _ok
    await stt.transcribe(b"w", MODEL_A, 30)
    assert fake.paths() == ["/v1/load", "/v1/audio/transcriptions"] * 2


async def test_read_timeout_and_http_errors_are_not_unreachable(
    fake: Fake, stt: WhisperCppSpeechToText
) -> None:
    await stt.load(MODEL_A)
    fake.handler = _raising(httpx2.ReadTimeout("slow", request=_request()))
    with pytest.raises(ProviderError) as slow:
        await stt.transcribe(b"w", MODEL_A, 7)
    assert not isinstance(slow.value, EngineUnreachable)
    assert slow.value.reason == "connection"
    timeout = fake.requests[-1].extensions["timeout"]
    assert timeout["read"] == 7
    assert timeout["connect"] == CONNECT_TIMEOUT_S

    fake.handler = lambda _r: httpx2.Response(500, json={"error": "failed to process audio"})
    with pytest.raises(ProviderError, match="failed to process audio") as failed:
        await stt.transcribe(b"w", MODEL_A, 30)
    assert not isinstance(failed.value, EngineUnreachable)
    assert failed.value.reason == "unavailable"

    fake.handler = _raising(httpx2.RemoteProtocolError("gone", request=_request()))
    with pytest.raises(ProviderError) as gone:
        await stt.transcribe(b"w", MODEL_A, 30)
    assert not isinstance(gone.value, EngineUnreachable)


async def test_bad_answer_is_a_provider_error(fake: Fake, stt: WhisperCppSpeechToText) -> None:
    await stt.load(MODEL_A)
    fake.handler = lambda _r: httpx2.Response(200, text="not json")
    with pytest.raises(ProviderError):
        await stt.transcribe(b"w", MODEL_A, 30)
    fake.handler = lambda _r: httpx2.Response(200, json={"nope": 1})
    with pytest.raises(ProviderError):
        await stt.transcribe(b"w", MODEL_A, 30)


async def test_running(fake: Fake, stt: WhisperCppSpeechToText) -> None:
    fake.handler = lambda _r: httpx2.Response(200, json={"status": "ok"})
    assert await stt.running() is True
    assert str(fake.requests[-1].url) == f"{BASE}/health"

    fake.handler = lambda _r: httpx2.Response(503, json={"status": "loading model"})
    assert await stt.running() is True

    fake.handler = lambda _r: httpx2.Response(404)
    assert await stt.running() is False

    fake.handler = _raising(httpx2.ConnectError("refused", request=_request()))
    assert await stt.running() is False

    fake.handler = _raising(httpx2.ReadTimeout("slow", request=_request()))
    assert await stt.running() is False


async def test_status(fake: Fake, stt: WhisperCppSpeechToText) -> None:
    fake.handler = lambda _r: httpx2.Response(200, json={"status": "ok"})
    ready = await stt.status(MODEL_A)
    assert (ready.base_url, ready.model) == (BASE, MODEL_A)
    assert (ready.reachable, ready.model_ready) == (True, True)

    fake.handler = lambda _r: httpx2.Response(503, json={"status": "loading model"})
    loading = await stt.status(MODEL_A)
    assert (loading.reachable, loading.model_ready) == (True, False)
    assert loading.detail == "whisper.cpp is loading a model."

    fake.handler = lambda _r: httpx2.Response(404)
    other = await stt.status(MODEL_A)
    assert (other.reachable, other.model_ready) == (False, False)

    fake.handler = _raising(httpx2.ConnectError("refused", request=_request()))
    down = await stt.status(MODEL_A)
    assert (down.reachable, down.model_ready) == (False, False)
    assert down.detail == f"Could not connect to {BASE}."


async def test_status_explains_other_failures(fake: Fake, stt: WhisperCppSpeechToText) -> None:
    fake.handler = _raising(httpx2.ReadTimeout("slow", request=_request()))
    slow = await stt.status(MODEL_A)
    assert (slow.reachable, slow.detail) == (False, f"{BASE} did not answer in time.")

    fake.handler = _raising(httpx2.RemoteProtocolError("gone", request=_request()))
    gone = await stt.status(MODEL_A)
    assert (gone.reachable, gone.detail) == (False, f"Could not connect to {BASE}.")


async def test_plain_text_error_is_reported(fake: Fake, stt: WhisperCppSpeechToText) -> None:
    await stt.load(MODEL_A)
    fake.handler = lambda _r: httpx2.Response(500, text="boom")

    with pytest.raises(ProviderError, match="boom"):
        await stt.transcribe(b"w", MODEL_A, 30)
