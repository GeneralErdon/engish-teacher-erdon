"""`/v1/speech`: a real `SpeechService` over the encrypted settings table and in-memory fakes of
Speaches, the models folder and the speech adapters."""

import asyncio
import io
import wave
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import NonCallableMagicMock, create_autospec

import httpx2
import pytest

from vt_api.adapters.openai_stt import OpenAISpeechToText
from vt_api.adapters.openai_tts import OpenAITextToSpeech
from vt_api.adapters.sql.database import Database
from vt_api.adapters.sql.speech_settings import SqlSpeechSettingsRepository
from vt_api.config import Settings
from vt_api.container import Container
from vt_api.main import create_app
from vt_api.services.learner import LearnerService
from vt_api.services.llm import LlmService
from vt_api.services.speech import SpeechService
from vt_contracts.speech import (
    DownloadProgress,
    ModelStatus,
    SpeechModels,
    SpeechSettings,
    SpeechSettingsView,
    Voice,
)

WHISPER = "Systran/faster-distil-whisper-small.en"
SMALL = "Systran/faster-whisper-small.en"
KOKORO = "speaches-ai/Kokoro-82M-v1.0-ONNX"
KOKORO_INT8 = "speaches-ai/Kokoro-82M-v1.0-ONNX-int8"
HEART = Voice(id="af_heart", name="Heart", accent="american", gender="female")
EMMA = Voice(id="bf_emma", name="Emma", accent="british", gender="female")


class FakeServer:
    def __init__(self, models: set[str]) -> None:
        self.models = models

    async def is_speaches(self) -> bool:
        return True

    async def installed(self) -> set[str]:
        return set(self.models)

    async def voices(self, model_id: str) -> list[Voice]:
        return [HEART, EMMA] if model_id.startswith(KOKORO) else []

    async def unload(self, model_id: str) -> None:
        return None


class FakeFiles:
    """A download that runs until the test cancels it."""

    def progress(self) -> tuple[str, DownloadProgress] | None:
        return None

    async def download(self, model_id: str) -> None:
        await asyncio.Event().wait()

    async def cancel(self) -> None:
        raise NotImplementedError

    async def delete(self, model_id: str) -> None:
        return None

    def cleanup(self) -> None:
        raise NotImplementedError


async def _pcm(*_: Any) -> AsyncIterator[bytes]:
    yield b"\x01\x00" * 100


def _status(model: str) -> ModelStatus:
    return ModelStatus(
        base_url="http://speech/v1", model=model, reachable=True, model_ready=True, detail=None
    )


@pytest.fixture
async def client(
    database: Database, learner_service: LearnerService, speech_defaults: SpeechSettings
) -> AsyncIterator[httpx2.AsyncClient]:
    installed = {WHISPER, SMALL, KOKORO, KOKORO_INT8}
    stt: NonCallableMagicMock = create_autospec(OpenAISpeechToText, instance=True)
    stt.status.side_effect = lambda model: _status(model)
    tts: NonCallableMagicMock = create_autospec(OpenAITextToSpeech, instance=True)
    tts.status.side_effect = lambda model: _status(model)
    tts.synthesize.side_effect = _pcm
    speech = SpeechService(
        repository=SqlSpeechSettingsRepository(database),
        stt=stt,
        tts=tts,
        recognition_server=FakeServer(installed),
        voice_server=FakeServer(installed),
        files=FakeFiles(),
        defaults=speech_defaults,
    )
    container = Container(
        llm=create_autospec(LlmService, instance=True),
        learner=learner_service,
        speech=speech,
    )
    app = create_app(Settings(_env_file=None), container=container)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http
    await speech.aclose()


def _settings(defaults: SpeechSettings, **changes: Any) -> dict[str, Any]:
    return {**defaults.model_dump(), **changes}


async def test_settings_round_trip(
    client: httpx2.AsyncClient, speech_defaults: SpeechSettings
) -> None:
    first = SpeechSettingsView.model_validate_json(
        (await client.get("/v1/speech/settings")).content
    )
    assert (first.source, first.stt_model) == ("environment", WHISPER)

    body = _settings(speech_defaults, stt_model=SMALL, tts_speed=1.1, max_turn_s=180)
    saved = await client.put("/v1/speech/settings", json=body)

    assert saved.status_code == 200
    view = SpeechSettingsView.model_validate_json((await client.get("/v1/speech/settings")).content)
    assert (view.source, view.stt_model, view.tts_speed, view.max_turn_s) == (
        "saved",
        SMALL,
        1.1,
        180,
    )


async def test_a_turn_shorter_than_30_seconds_is_rejected(
    client: httpx2.AsyncClient, speech_defaults: SpeechSettings
) -> None:
    response = await client.put(
        "/v1/speech/settings", json=_settings(speech_defaults, max_turn_s=10)
    )

    assert response.status_code == 422


async def test_a_model_that_is_not_installed_is_refused_with_its_message(
    client: httpx2.AsyncClient, speech_defaults: SpeechSettings
) -> None:
    body = _settings(speech_defaults, stt_model="Systran/faster-whisper-tiny.en")

    response = await client.put("/v1/speech/settings", json=body)

    assert response.status_code == 422
    assert "not installed" in response.json()["detail"]


async def test_a_download_starts_with_202_and_a_second_model_waits_with_409(
    client: httpx2.AsyncClient,
) -> None:
    first = await client.post("/v1/speech/models/whisper-tiny-en/download", json={})
    models = SpeechModels.model_validate_json(first.content)

    assert first.status_code == 202
    assert {m.key: m.state for m in models.models}["whisper-tiny-en"] == "downloading"

    second = await client.post("/v1/speech/models/piper-alba/download", json={})

    assert second.status_code == 409
    assert "downloading" in second.json()["detail"]


async def test_an_unknown_model_is_a_404(client: httpx2.AsyncClient) -> None:
    response = await client.post("/v1/speech/models/nope/download", json={})

    assert response.status_code == 404


async def test_cancelling_a_download_answers_204(client: httpx2.AsyncClient) -> None:
    await client.post("/v1/speech/models/whisper-tiny-en/download", json={})

    response = await client.delete("/v1/speech/models/whisper-tiny-en/download")

    assert response.status_code == 204
    models = SpeechModels.model_validate_json((await client.get("/v1/speech/models")).content)
    assert {m.key: m.state for m in models.models}["whisper-tiny-en"] == "available"


async def test_the_default_model_cannot_be_uninstalled(client: httpx2.AsyncClient) -> None:
    models = SpeechModels.model_validate_json((await client.get("/v1/speech/models")).content)
    default = next(m for m in models.models if m.default and m.kind == "recognition")

    response = await client.delete(f"/v1/speech/models/{default.key}")

    assert response.status_code == 409


async def test_an_installed_model_is_uninstalled_with_204(client: httpx2.AsyncClient) -> None:
    response = await client.delete("/v1/speech/models/whisper-small-en")

    assert response.status_code == 204


async def test_voices_are_those_of_the_model(client: httpx2.AsyncClient) -> None:
    kokoro = await client.get("/v1/speech/voices", params={"model": KOKORO})
    other = await client.get("/v1/speech/voices", params={"model": "unknown"})

    assert [v["id"] for v in kokoro.json()] == ["af_heart", "bf_emma"]
    assert other.json() == []


async def test_a_preview_is_a_wav(client: httpx2.AsyncClient) -> None:
    response = await client.post(
        "/v1/speech/preview", json={"model": KOKORO, "voice": "af_heart", "speed": 1.0}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(response.content)) as wav:
        assert wav.getnframes() == 100


async def test_the_status_reports_the_selected_models(
    client: httpx2.AsyncClient, speech_defaults: SpeechSettings
) -> None:
    await client.put("/v1/speech/settings", json=_settings(speech_defaults, stt_model=SMALL))

    status = (await client.get("/v1/speech/status")).json()

    assert status["recognition"]["model"] == SMALL
    assert status["synthesis"]["model"] == KOKORO


def test_the_preview_is_declared_as_binary_in_openapi() -> None:
    app = create_app(Settings(_env_file=None), container=create_autospec(Container, instance=True))

    ok = app.openapi()["paths"]["/v1/speech/preview"]["post"]["responses"]["200"]

    assert "audio/wav" in ok["content"]
