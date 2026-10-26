"""The Speaches model server against a fake (`httpx2.MockTransport`)."""

from collections.abc import AsyncIterator, Callable

import httpx2
import pytest

from vt_api.adapters.speaches import SpeachesServer
from vt_api.domain.llm import ProviderError
from vt_contracts.speech import Voice

KOKORO = "speaches-ai/Kokoro-82M-v1.0-ONNX"
PIPER = "speaches-ai/piper-en_US-lessac-medium"
type Handler = Callable[[httpx2.Request], httpx2.Response]

REGISTRY = {
    "data": [
        {
            "id": KOKORO,
            "voices": [
                {"name": "af_heart", "language": "en-us", "gender": "female", "id": "af_heart"},
                {"name": "bm_george", "language": "en-gb", "gender": "male", "id": "bm_george"},
                {"name": "jf_alpha", "language": "ja", "gender": "female", "id": "jf_alpha"},
            ],
        },
        {"id": PIPER, "voices": [{"name": "lessac", "id": "lessac"}]},
    ]
}


class Fake:
    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.handler: Handler = lambda _request: httpx2.Response(500)

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.handler(request)


@pytest.fixture
def fake() -> Fake:
    return Fake()


@pytest.fixture
async def server(fake: Fake) -> AsyncIterator[SpeachesServer]:
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(fake))
    yield SpeachesServer(http, "http://localhost:8000/v1")
    await http.aclose()


async def test_installed_lists_local_model_ids(fake: Fake, server: SpeachesServer) -> None:
    fake.handler = lambda _r: httpx2.Response(
        200, json={"data": [{"id": "a/one", "task": "x"}, {"id": "b/two"}]}
    )

    assert await server.installed() == {"a/one", "b/two"}
    assert str(fake.requests[0].url) == "http://localhost:8000/v1/models"


async def test_unreachable_server_raises_provider_error(fake: Fake, server: SpeachesServer) -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    fake.handler = refuse

    with pytest.raises(ProviderError) as caught:
        await server.installed()

    assert caught.value.reason == "connection"
    assert "http://localhost:8000" in caught.value.message


async def test_timeout_raises_provider_error(fake: Fake, server: SpeachesServer) -> None:
    def slow(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    fake.handler = slow

    with pytest.raises(ProviderError) as caught:
        await server.installed()

    assert caught.value.reason == "connection"
    assert "in time" in caught.value.message


async def test_server_error_raises_provider_error(fake: Fake, server: SpeachesServer) -> None:
    fake.handler = lambda _r: httpx2.Response(503, text="busy")

    with pytest.raises(ProviderError) as caught:
        await server.installed()

    assert caught.value.reason == "unavailable"


async def test_voices_are_english_with_accent_and_gender(
    fake: Fake, server: SpeachesServer
) -> None:
    fake.handler = lambda _r: httpx2.Response(200, json=REGISTRY)

    assert await server.voices(KOKORO) == [
        Voice(id="af_heart", name="af_heart", accent="american", gender="female"),
        Voice(id="bm_george", name="bm_george", accent="british", gender="male"),
    ]
    assert fake.requests[0].url.params["task"] == "text-to-speech"


async def test_voices_without_language_or_gender_are_kept(
    fake: Fake, server: SpeachesServer
) -> None:
    fake.handler = lambda _r: httpx2.Response(200, json=REGISTRY)

    assert await server.voices(PIPER) == [
        Voice(id="lessac", name="lessac", accent=None, gender=None)
    ]


async def test_voices_of_unknown_model_are_empty(fake: Fake, server: SpeachesServer) -> None:
    fake.handler = lambda _r: httpx2.Response(200, json=REGISTRY)

    assert await server.voices("nobody/home") == []


async def test_registry_is_fetched_once(fake: Fake, server: SpeachesServer) -> None:
    fake.handler = lambda _r: httpx2.Response(200, json=REGISTRY)

    await server.voices(KOKORO)
    await server.voices(PIPER)

    assert len(fake.requests) == 1


async def test_failed_registry_is_not_cached(fake: Fake, server: SpeachesServer) -> None:
    fake.handler = lambda _r: httpx2.Response(500)
    with pytest.raises(ProviderError):
        await server.voices(KOKORO)

    fake.handler = lambda _r: httpx2.Response(200, json=REGISTRY)

    assert len(await server.voices(KOKORO)) == 2


async def test_is_speaches_true_when_registry_answers(fake: Fake, server: SpeachesServer) -> None:
    fake.handler = lambda _r: httpx2.Response(200, json=REGISTRY)

    assert await server.is_speaches() is True
    assert str(fake.requests[0].url) == "http://localhost:8000/v1/registry"


async def test_is_speaches_false_for_other_servers(fake: Fake, server: SpeachesServer) -> None:
    fake.handler = lambda _r: httpx2.Response(404)

    assert await server.is_speaches() is False


async def test_is_speaches_false_for_non_speaches_json(fake: Fake, server: SpeachesServer) -> None:
    fake.handler = lambda _r: httpx2.Response(200, json={"hello": 1})

    assert await server.is_speaches() is False


async def test_is_speaches_false_when_unreachable(fake: Fake, server: SpeachesServer) -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    fake.handler = refuse

    assert await server.is_speaches() is False


async def test_unload_deletes_the_loaded_model(fake: Fake, server: SpeachesServer) -> None:
    fake.handler = lambda _r: httpx2.Response(200)

    await server.unload(KOKORO)

    request = fake.requests[0]
    assert request.method == "DELETE"
    assert request.url.raw_path == b"/api/ps/speaches-ai/Kokoro-82M-v1.0-ONNX"


async def test_unload_ignores_not_loaded(fake: Fake, server: SpeachesServer) -> None:
    fake.handler = lambda _r: httpx2.Response(404)

    await server.unload(KOKORO)


async def test_unload_failure_raises_provider_error(fake: Fake, server: SpeachesServer) -> None:
    fake.handler = lambda _r: httpx2.Response(500, text="boom")

    with pytest.raises(ProviderError):
        await server.unload(KOKORO)


async def test_non_json_answer_raises_provider_error(fake: Fake, server: SpeachesServer) -> None:
    fake.handler = lambda _r: httpx2.Response(200, text="<html>hi</html>")

    with pytest.raises(ProviderError):
        await server.installed()


async def test_is_speaches_false_for_non_json_answer(fake: Fake, server: SpeachesServer) -> None:
    fake.handler = lambda _r: httpx2.Response(200, text="<html>hi</html>")

    assert await server.is_speaches() is False


@pytest.mark.parametrize("body", [{"hello": 1}, {"data": [{"name": "no id"}]}, {"data": [1]}])
async def test_unexpected_models_shape_raises_provider_error(
    fake: Fake, server: SpeachesServer, body: dict[str, object]
) -> None:
    fake.handler = lambda _r: httpx2.Response(200, json=body)

    with pytest.raises(ProviderError):
        await server.installed()


async def test_unexpected_registry_shape_raises_provider_error(
    fake: Fake, server: SpeachesServer
) -> None:
    fake.handler = lambda _r: httpx2.Response(200, json=[1, 2])

    with pytest.raises(ProviderError):
        await server.voices(KOKORO)
