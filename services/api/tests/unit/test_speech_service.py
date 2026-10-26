"""`SpeechService` over in-memory fakes of Speaches and the models folder, with the real settings
table."""

import asyncio
import io
import itertools
import wave
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import NonCallableMagicMock, create_autospec

import httpx2
import pytest

from vt_api.adapters.openai_stt import OpenAISpeechToText
from vt_api.adapters.openai_tts import OpenAITextToSpeech
from vt_api.adapters.speaches import SpeachesServer
from vt_api.adapters.sql.database import Database
from vt_api.adapters.sql.speech_settings import SqlSpeechSettingsRepository
from vt_api.domain.llm import ProviderError
from vt_api.domain.speech import (
    SessionSpeech,
    SpeechSettingsError,
    VoiceChoice,
    transcription_timeout_s,
)
from vt_api.services.speech import PREVIEW_TEXT, SpeechService
from vt_contracts.speech import (
    DownloadProgress,
    ModelStatus,
    SpeechModel,
    SpeechModels,
    SpeechSettings,
    SpeechSettingsView,
    Voice,
    VoicePreview,
)

WHISPER = "Systran/faster-distil-whisper-small.en"  # the default
SMALL = "Systran/faster-whisper-small.en"
TINY = "Systran/faster-whisper-tiny.en"
KOKORO = "speaches-ai/Kokoro-82M-v1.0-ONNX"  # the default
KOKORO_INT8 = "speaches-ai/Kokoro-82M-v1.0-ONNX-int8"
ALBA = "speaches-ai/piper-en_GB-alba-medium"

HEART = Voice(id="af_heart", name="Heart", accent="american", gender="female")
EMMA = Voice(id="bf_emma", name="Emma", accent="british", gender="female")
ALBA_VOICE = Voice(id="alba", name="Alba", accent="british", gender="female")
UNREACHABLE = ProviderError("connection", "Could not connect to http://localhost:8000.")


class FakeServer:
    """One kind's Speaches. `models` is the folder it reads, shared with `FakeFiles`."""

    def __init__(self, models: set[str], calls: list[str]) -> None:
        self.models = models
        self.calls = calls
        self.voices_of: dict[str, list[Voice]] = {
            KOKORO: [HEART, EMMA],
            KOKORO_INT8: [EMMA, HEART],
            ALBA: [ALBA_VOICE],
        }
        self.speaches = True
        self.error: ProviderError | None = None
        """Raised by every call but `unload`: the server does not answer."""
        self.unload_error: ProviderError | None = None
        self.held: str | None = None
        """A model whose `voices` call waits for `answer_held`, like a slow HTTP call."""
        self.held_asked = asyncio.Event()
        self.answer_held = asyncio.Event()

    async def is_speaches(self) -> bool:
        await asyncio.sleep(0)  # an HTTP call: other requests run meanwhile
        return self.speaches and self.error is None

    async def installed(self) -> set[str]:
        await asyncio.sleep(0)
        self._answer()
        return set(self.models)

    async def voices(self, model_id: str) -> list[Voice]:
        self._answer()
        if model_id == self.held:
            self.held_asked.set()
            await self.answer_held.wait()
        return self.voices_of.get(model_id, [])

    async def unload(self, model_id: str) -> None:
        self.calls.append(f"unload {model_id}")
        if self.unload_error is not None:
            raise self.unload_error

    def _answer(self) -> None:
        if self.error is not None:
            raise self.error


class FakeFiles:
    """Downloads that run until `finish()`. A finished model lands in `models`, the folder the
    servers read, unless `shared` is off."""

    def __init__(self, models: set[str], calls: list[str]) -> None:
        self.models = models
        self.calls = calls
        self.shared = True
        self.partial: set[str] = set()
        """Half-written folders, as an api killed mid-download leaves them."""
        self.error: Exception | None = None
        self.delete_error: SpeechSettingsError | None = None
        self.task: asyncio.Task[Any] | None = None
        """The task the running download is awaited in: the service's."""
        self._progress: tuple[str, DownloadProgress] | None = None
        self._entered = asyncio.Event()
        self._release = asyncio.Event()

    def progress(self) -> tuple[str, DownloadProgress] | None:
        return self._progress

    async def download(self, model_id: str) -> None:
        self._release = asyncio.Event()
        self.task = asyncio.current_task()
        self._progress = (model_id, DownloadProgress(done_bytes=50, total_bytes=200))
        self._entered.set()
        try:
            await self._release.wait()
        finally:
            self._entered.clear()
            self.task = None
            self._progress = None
        if self.error is not None:
            raise self.error
        self.partial.discard(model_id)
        if self.shared:
            self.models.add(model_id)

    async def cancel(self) -> None:
        raise NotImplementedError  # the service cancels the task it owns

    async def delete(self, model_id: str) -> None:
        self.calls.append(f"delete {model_id}")
        if self.delete_error is not None:
            raise self.delete_error

    async def incomplete(self) -> set[str]:
        return set(self.partial)

    def cleanup(self) -> None:
        raise NotImplementedError  # the adapter runs it when it is built

    async def started(self) -> asyncio.Task[Any]:
        """The service's task, once it is inside `download()`."""
        await self._entered.wait()
        assert self.task is not None
        return self.task

    def release(self) -> None:
        """Let the running download end."""
        self._release.set()

    async def finish(self) -> asyncio.Task[Any]:
        """Let the download end, and wait until the service has acted on it."""
        task = await self.started()
        self.release()
        await asyncio.wait({task})
        return task


class Clock:
    """`time.perf_counter` for the service: the next of `readings`."""

    def __init__(self) -> None:
        self.readings: Iterator[float] = itertools.repeat(0.0)

    def __call__(self) -> float:
        return next(self.readings)


@pytest.fixture
def calls() -> list[str]:
    """What the fakes were asked to change, in order."""
    return []


@pytest.fixture
def installed() -> set[str]:
    """The folder Speaches reads: the two defaults, as `just voice` preloads them."""
    return {WHISPER, KOKORO}


@pytest.fixture
def recognition(installed: set[str], calls: list[str]) -> FakeServer:
    return FakeServer(installed, calls)


@pytest.fixture
def voice_server(installed: set[str], calls: list[str]) -> FakeServer:
    return FakeServer(installed, calls)


@pytest.fixture
def files(installed: set[str], calls: list[str]) -> FakeFiles:
    return FakeFiles(installed, calls)


@pytest.fixture
def stt() -> NonCallableMagicMock:
    mock: NonCallableMagicMock = create_autospec(OpenAISpeechToText, instance=True)
    return mock


@pytest.fixture
def tts() -> NonCallableMagicMock:
    mock: NonCallableMagicMock = create_autospec(OpenAITextToSpeech, instance=True)
    return mock


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def service(
    database: Database,
    speech_defaults: SpeechSettings,
    recognition: FakeServer,
    voice_server: FakeServer,
    files: FakeFiles,
    stt: NonCallableMagicMock,
    tts: NonCallableMagicMock,
    clock: Clock,
) -> AsyncIterator[SpeechService]:
    service = SpeechService(
        repository=SqlSpeechSettingsRepository(database),
        stt=stt,
        tts=tts,
        recognition_server=recognition,
        voice_server=voice_server,
        files=files,
        defaults=speech_defaults,
        clock=clock,
    )
    yield service
    await service.aclose()


def _row(models: SpeechModels, model_id: str) -> SpeechModel:
    return next(model for model in models.models if model.model_id == model_id)


async def _stream(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


async def _failing_stream() -> AsyncIterator[bytes]:
    yield b"\x01\x00"
    raise UNREACHABLE


async def test_view_defaults_then_saved(
    service: SpeechService, speech_defaults: SpeechSettings, installed: set[str]
) -> None:
    assert await service.view() == SpeechSettingsView(
        **speech_defaults.model_dump(), source="environment"
    )

    installed.add(SMALL)
    chosen = speech_defaults.model_copy(
        update={"stt_model": SMALL, "tts_speed": 1.1, "max_turn_s": 180}
    )

    assert await service.save(chosen) == SpeechSettingsView(**chosen.model_dump(), source="saved")
    assert await service.view() == SpeechSettingsView(**chosen.model_dump(), source="saved")


@pytest.mark.parametrize(
    "change",
    [
        {"stt_model": SMALL},
        {"tts_model": ALBA, "tts_voice": "alba"},
        {"stt_model": KOKORO},  # installed, but it speaks: not a recognition model
    ],
)
async def test_save_refuses_a_model_that_is_not_installed(
    service: SpeechService, speech_defaults: SpeechSettings, change: dict[str, str]
) -> None:
    model = next(iter(change.values()))

    with pytest.raises(SpeechSettingsError) as refused:
        await service.save(speech_defaults.model_copy(update=change))

    assert refused.value.status == 422
    assert model in refused.value.message
    assert (await service.view()).source == "environment"


async def test_save_refuses_a_voice_of_another_model(
    service: SpeechService, speech_defaults: SpeechSettings, installed: set[str]
) -> None:
    installed.add(ALBA)

    with pytest.raises(SpeechSettingsError) as refused:
        await service.save(speech_defaults.model_copy(update={"tts_model": ALBA}))  # af_heart

    assert refused.value.status == 422
    assert "af_heart" in refused.value.message


async def test_speed_saves_while_the_saved_model_is_missing(
    service: SpeechService,
    speech_defaults: SpeechSettings,
    installed: set[str],
    voice_server: FakeServer,
) -> None:
    """Only what changed is checked: a saved model wiped by hand, or a saved voice the server
    no longer lists, does not block the other settings."""
    installed.add(SMALL)
    chosen = speech_defaults.model_copy(update={"stt_model": SMALL})
    await service.save(chosen)
    installed.discard(SMALL)
    voice_server.voices_of[KOKORO] = [EMMA]

    saved = await service.save(chosen.model_copy(update={"tts_speed": 0.8}))

    assert (saved.stt_model, saved.tts_speed, saved.missing) == (SMALL, 0.8, ["recognition"])
    assert (await service.view()).tts_speed == 0.8


async def test_turn_length_saves_while_speaches_is_down(
    service: SpeechService,
    speech_defaults: SpeechSettings,
    installed: set[str],
    recognition: FakeServer,
    voice_server: FakeServer,
) -> None:
    installed.update({SMALL, KOKORO_INT8})
    chosen = speech_defaults.model_copy(update={"stt_model": SMALL, "tts_model": KOKORO_INT8})
    await service.save(chosen)
    recognition.error = voice_server.error = UNREACHABLE

    saved = await service.save(chosen.model_copy(update={"max_turn_s": 300}))

    assert (saved.stt_model, saved.max_turn_s, saved.missing) == (SMALL, 300, [])
    # The defaults are always installed: going back to them needs no check either.
    saved = await service.save(speech_defaults)
    assert (saved.stt_model, saved.tts_model, saved.source) == (WHISPER, KOKORO, "saved")


async def test_changing_a_model_or_the_voice_still_checks_it(
    service: SpeechService, speech_defaults: SpeechSettings, installed: set[str]
) -> None:
    installed.add(SMALL)
    chosen = speech_defaults.model_copy(update={"stt_model": SMALL})
    await service.save(chosen)
    installed.discard(SMALL)

    for change in ({"stt_model": TINY}, {"tts_voice": "nobody"}):
        with pytest.raises(SpeechSettingsError) as refused:
            await service.save(chosen.model_copy(update=change))
        assert refused.value.status == 422
    assert (await service.view()).stt_model == SMALL


async def test_models_merge_catalog_installed_downloading_and_measured(
    service: SpeechService,
    installed: set[str],
    files: FakeFiles,
    stt: NonCallableMagicMock,
    clock: Clock,
) -> None:
    installed.add(SMALL)
    await service.download("whisper-tiny-en", activate=False)
    await files.started()
    stt.transcribe.return_value = "Hello"
    clock.readings = iter([0.0, 1.0, 5.0, 8.0])  # 1000 ms, then 3000 ms
    await service.transcribe(b"wav", 2.0, WHISPER)
    await service.transcribe(b"wav", 4.0, WHISPER)

    models = await service.models()

    assert _row(models, TINY) == SpeechModel(
        key="whisper-tiny-en",
        kind="recognition",
        model_id=TINY,
        label="Whisper tiny (English)",
        hint="Fastest, least accurate",
        approx_mb=78,
        english_only=True,
        state="downloading",
        download=DownloadProgress(done_bytes=50, total_bytes=200),
        default=False,
        selected=False,
        from_configuration=False,
        ms_per_audio_s=None,
    )
    assert (_row(models, SMALL).state, _row(models, SMALL).download) == ("installed", None)
    assert _row(models, "Systran/faster-whisper-base.en").state == "available"
    assert _row(models, WHISPER).ms_per_audio_s == 666.7  # 4000 ms / 6 s
    assert [(m.kind, m.model_id) for m in models.models if m.selected] == [
        ("recognition", WHISPER),
        ("voice", KOKORO),
    ]
    assert [m.model_id for m in models.models if m.default] == [WHISPER, KOKORO]
    assert len(models.models) == 14
    assert not any(m.from_configuration for m in models.models)
    assert (models.recognition_manageable, models.voice_manageable) == (True, True)
    assert models.last_error is None


async def test_download_with_activate_selects_the_model_when_done(
    service: SpeechService, files: FakeFiles
) -> None:
    started = await service.download("whisper-small-en", activate=True)

    assert _row(started, SMALL).state == "downloading"
    view = await service.view()
    assert (view.stt_model, view.pending) == (WHISPER, [SMALL])

    await files.finish()

    view = await service.view()
    assert (view.stt_model, view.source, view.pending) == (SMALL, "saved", [])
    row = _row(await service.models(), SMALL)
    assert (row.state, row.selected) == ("installed", True)


@pytest.mark.parametrize("delete_error", [None, SpeechSettingsError(500, "Permission denied")])
async def test_download_seen_by_speaches_is_required(
    service: SpeechService,
    files: FakeFiles,
    calls: list[str],
    delete_error: SpeechSettingsError | None,
) -> None:
    """Review Focus 1: the api downloaded into a folder Speaches does not read. Nothing can use
    those files, so they go; failing to remove them does not hide why."""
    files.shared = False
    files.delete_error = delete_error
    await service.download("whisper-small-en", activate=True)

    await files.finish()

    assert calls == [f"delete {SMALL}"]
    models = await service.models()
    assert models.last_error == (
        "Downloaded, but Speaches does not see it: VT_SPEECH_MODELS_DIR must be the folder "
        "Speaches reads (see docs/configuration.md)"
    )
    assert _row(models, SMALL).state == "available"
    view = await service.view()
    assert (view.stt_model, view.source, view.pending) == (WHISPER, "environment", [])


async def test_switching_to_piper_picks_its_voice(service: SpeechService, files: FakeFiles) -> None:
    """Review Focus 3. Kokoro int8 has the current voice (not first), Piper Alba does not."""
    await service.download("kokoro-int8", activate=True)
    await files.finish()

    view = await service.view()
    assert (view.tts_model, view.tts_voice) == (KOKORO_INT8, "af_heart")

    await service.download("piper-alba", activate=True)
    await files.finish()

    view = await service.view()
    assert (view.tts_model, view.tts_voice) == (ALBA, "alba")


async def test_second_download_conflicts_same_one_updates_intent(service: SpeechService) -> None:
    """Review Focus 5: one download at a time, and clicking Download twice is fine."""
    await service.download("whisper-small-en", activate=False)
    assert (await service.view()).pending == []

    await service.download("whisper-small-en", activate=True)
    assert (await service.view()).pending == [SMALL]

    for other in ("whisper-tiny-en", "piper-alba"):
        with pytest.raises(SpeechSettingsError) as refused:
            await service.download(other, activate=False)
        assert refused.value.status == 409
    assert _row(await service.models(), SMALL).state == "downloading"


async def test_two_downloads_at_once_start_only_one(
    service: SpeechService, files: FakeFiles
) -> None:
    """Two requests that both found no download running."""
    results = await asyncio.gather(
        service.download("whisper-small-en", activate=False),
        service.download("whisper-tiny-en", activate=False),
        return_exceptions=True,
    )

    refusals = [r for r in results if isinstance(r, SpeechSettingsError)]
    assert [r.status for r in refusals] == [409]
    await files.started()
    assert [m.model_id for m in (await service.models()).models if m.state == "downloading"] == [
        SMALL
    ]


async def test_cancelling_twice_waits_for_the_one_cancel(
    service: SpeechService, files: FakeFiles
) -> None:
    await service.download("whisper-small-en", activate=True)
    task = await files.started()

    await asyncio.gather(
        service.cancel_download("whisper-small-en"), service.cancel_download("whisper-small-en")
    )

    assert task.cancelled()
    assert (await service.view()).pending == []


async def test_uninstall_refuses_default_selected_and_downloading(
    service: SpeechService, speech_defaults: SpeechSettings, installed: set[str], calls: list[str]
) -> None:
    """Review Focus 5."""
    installed.add(SMALL)
    await service.save(speech_defaults.model_copy(update={"stt_model": SMALL}))
    await service.download("whisper-tiny-en", activate=False)
    refusals: dict[str, str] = {}

    for key in ("distil-whisper-small-en", "kokoro", "whisper-small-en", "whisper-tiny-en"):
        with pytest.raises(SpeechSettingsError) as refused:
            await service.uninstall(key)
        assert refused.value.status == 409
        refusals[key] = refused.value.message

    assert "default" in refusals["distil-whisper-small-en"]
    assert "in use" in refusals["whisper-small-en"]
    assert "cancel" in refusals["whisper-tiny-en"]
    assert calls == []


async def test_uninstall_unloads_then_deletes(
    service: SpeechService, installed: set[str], calls: list[str]
) -> None:
    installed.add(SMALL)

    await service.uninstall("whisper-small-en")

    assert calls == [f"unload {SMALL}", f"delete {SMALL}"]


async def test_uninstall_deletes_even_when_unloading_fails(
    service: SpeechService, installed: set[str], recognition: FakeServer, calls: list[str]
) -> None:
    installed.add(SMALL)
    recognition.unload_error = UNREACHABLE

    await service.uninstall("whisper-small-en")

    assert calls == [f"unload {SMALL}", f"delete {SMALL}"]


async def test_unknown_models_are_404(service: SpeechService) -> None:
    with pytest.raises(SpeechSettingsError) as refused:
        await service.download("whisper-huge", activate=True)
    assert refused.value.status == 404

    with pytest.raises(SpeechSettingsError) as refused:
        await service.uninstall("whisper-huge")
    assert refused.value.status == 404


async def test_choosing_another_model_drops_the_pending_activation(
    service: SpeechService, speech_defaults: SpeechSettings, installed: set[str], files: FakeFiles
) -> None:
    installed.add(TINY)
    await service.download("whisper-small-en", activate=True)

    await service.save(speech_defaults.model_copy(update={"tts_speed": 1.2}))
    assert (await service.view()).pending == [SMALL]  # the model did not change

    await service.save(speech_defaults.model_copy(update={"stt_model": TINY}))
    assert (await service.view()).pending == []

    await files.finish()

    assert (await service.view()).stt_model == TINY  # the latest choice wins
    assert _row(await service.models(), SMALL).state == "installed"


@pytest.mark.parametrize(
    ("change", "final"),
    [
        ({"tts_speed": 1.2}, (ALBA, "alba", 1.2)),  # the activation still applies, on top
        ({"tts_model": KOKORO_INT8}, (KOKORO_INT8, "af_heart", 0.95)),  # the latest choice
    ],
)
async def test_a_save_while_a_download_activates_is_kept(
    service: SpeechService,
    speech_defaults: SpeechSettings,
    installed: set[str],
    voice_server: FakeServer,
    files: FakeFiles,
    change: dict[str, object],
    final: tuple[str, str, float],
) -> None:
    """The learner saves while the activation asks Speaches for the new model's voices."""
    installed.add(KOKORO_INT8)
    voice_server.held = ALBA
    await service.download("piper-alba", activate=True)
    task = await files.started()
    files.release()
    await voice_server.held_asked.wait()

    await service.save(speech_defaults.model_copy(update=change))
    voice_server.answer_held.set()
    await asyncio.wait({task})

    view = await service.view()
    assert (view.tts_model, view.tts_voice, view.tts_speed) == final


async def test_cancel_drops_the_intent(service: SpeechService, files: FakeFiles) -> None:
    await service.download("whisper-small-en", activate=True)
    task = await files.started()

    await service.cancel_download("whisper-small-en")

    assert task.cancelled()
    view = await service.view()
    assert (view.stt_model, view.pending) == (WHISPER, [])
    models = await service.models()
    assert (_row(models, SMALL).state, models.last_error) == ("available", None)

    await service.cancel_download("whisper-small-en")  # nothing to cancel
    await service.download("whisper-tiny-en", activate=False)  # the next one may start


async def test_cancelling_another_model_conflicts(service: SpeechService, files: FakeFiles) -> None:
    """A stale tab cancels a download that has since ended and been replaced by another."""
    await service.download("whisper-small-en", activate=True)
    task = await files.started()

    with pytest.raises(SpeechSettingsError) as refused:
        await service.cancel_download("whisper-tiny-en")
    assert refused.value.status == 409
    with pytest.raises(SpeechSettingsError) as refused:
        await service.cancel_download("whisper-huge")
    assert refused.value.status == 404

    assert not task.done()
    assert (await service.view()).pending == [SMALL]


@pytest.mark.parametrize("missing", ["files", "speaches"])
async def test_not_manageable_without_files_or_speaches(
    missing: str,
    database: Database,
    speech_defaults: SpeechSettings,
    installed: set[str],
    recognition: FakeServer,
    voice_server: FakeServer,
    files: FakeFiles,
    stt: NonCallableMagicMock,
    tts: NonCallableMagicMock,
    calls: list[str],
) -> None:
    installed.add(SMALL)
    recognition.speaches = voice_server.speaches = missing != "speaches"
    service = SpeechService(
        repository=SqlSpeechSettingsRepository(database),
        stt=stt,
        tts=tts,
        recognition_server=recognition,
        voice_server=voice_server,
        files=None if missing == "files" else files,
        defaults=speech_defaults,
    )

    models = await service.models()

    assert (models.recognition_manageable, models.voice_manageable) == (False, False)
    assert _row(models, SMALL).state == "installed"
    with pytest.raises(SpeechSettingsError) as refused:
        await service.download("whisper-tiny-en", activate=True)
    assert refused.value.status == 409
    with pytest.raises(SpeechSettingsError) as refused:
        await service.uninstall("whisper-small-en")
    assert refused.value.status == 409
    assert (files.task, calls) == (None, [])


async def test_for_session_falls_back_to_default_when_missing(
    service: SpeechService, installed: set[str]
) -> None:
    installed.update({SMALL, ALBA})
    await service.save(
        SpeechSettings(
            stt_model=SMALL, tts_model=ALBA, tts_voice="alba", tts_speed=1.1, max_turn_s=180
        )
    )
    assert await service.for_session() == SessionSpeech(
        SMALL, VoiceChoice(ALBA, "alba", 1.1, 24_000), 180
    )

    installed.difference_update({SMALL, ALBA})  # removed with Speaches' own tools

    assert await service.for_session() == SessionSpeech(
        WHISPER, VoiceChoice(KOKORO, "af_heart", 1.1), 180, missing=("recognition", "voice")
    )
    view = await service.view()
    assert (view.stt_model, view.tts_model, view.missing) == (SMALL, ALBA, ["recognition", "voice"])


async def test_preview_is_a_wav_of_the_sample(
    service: SpeechService, tts: NonCallableMagicMock
) -> None:
    tts.synthesize.side_effect = lambda _text, _voice: _stream(b"\x01\x00", b"\x02\x00")

    audio = await service.preview(VoicePreview(model=ALBA, voice="alba", speed=0.8))

    assert audio[:4] == b"RIFF"
    with wave.open(io.BytesIO(audio)) as wav:
        assert (wav.getframerate(), wav.readframes(2)) == (24_000, b"\x01\x00\x02\x00")
    assert PREVIEW_TEXT == "Hi! I'm your English tutor. Shall we practise together?"
    tts.synthesize.assert_called_once_with(PREVIEW_TEXT, VoiceChoice(ALBA, "alba", 0.8, 24_000))


async def test_transcribe_uses_the_growing_timeout(
    service: SpeechService, stt: NonCallableMagicMock
) -> None:
    stt.transcribe.return_value = "Hello there"

    assert await service.transcribe(b"wav", 90.0, SMALL) == "Hello there"

    stt.transcribe.assert_awaited_once_with(b"wav", SMALL, transcription_timeout_s(90.0))


async def test_a_failed_transcription_is_not_measured(
    service: SpeechService, stt: NonCallableMagicMock
) -> None:
    stt.transcribe.side_effect = UNREACHABLE

    with pytest.raises(ProviderError):
        await service.transcribe(b"wav", 2.0, WHISPER)

    assert _row(await service.models(), WHISPER).ms_per_audio_s is None


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (SpeechSettingsError(507, "Not enough disk space."), "Not enough disk space."),
        (OSError("Read-only file system"), f"Downloading {SMALL} failed: Read-only file system"),
    ],
)
async def test_a_failed_download_is_reported_and_drops_the_intent(
    service: SpeechService, files: FakeFiles, error: Exception, message: str
) -> None:
    files.error = error
    await service.download("whisper-small-en", activate=True)

    task = await files.finish()

    assert task.exception() is None  # never an unretrieved task exception
    models = await service.models()
    assert (models.last_error, _row(models, SMALL).state) == (message, "available")
    view = await service.view()
    assert (view.stt_model, view.pending) == (WHISPER, [])

    await service.download("whisper-small-en", activate=False)
    assert (await service.models()).last_error is None  # until the next one starts


async def test_models_survive_a_server_that_does_not_answer(
    service: SpeechService, recognition: FakeServer
) -> None:
    recognition.error = UNREACHABLE

    models = await service.models()

    assert {m.state for m in models.models if m.kind == "recognition"} == {"available"}
    assert (_row(models, WHISPER).default, _row(models, WHISPER).selected) == (True, True)
    assert (models.recognition_manageable, models.voice_manageable) == (False, True)
    with pytest.raises(SpeechSettingsError) as refused:
        await service.download("whisper-small-en", activate=True)
    assert refused.value.status == 409


async def test_models_ask_the_speaches_registry_once_it_answers(
    database: Database,
    speech_defaults: SpeechSettings,
    files: FakeFiles,
    stt: NonCallableMagicMock,
    tts: NonCallableMagicMock,
) -> None:
    """The UI polls the models every second while a download runs; a registry that fails
    once is asked again, so the kinds become manageable when it answers."""
    registry: list[httpx2.Request] = []
    answers = iter([httpx2.Response(503), httpx2.Response(503)])

    def speaches(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/v1/models":
            return httpx2.Response(200, json={"data": [{"id": WHISPER}, {"id": KOKORO}]})
        registry.append(request)
        return next(answers, httpx2.Response(200, json={"data": []}))

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(speaches)) as http:
        service = SpeechService(
            repository=SqlSpeechSettingsRepository(database),
            stt=stt,
            tts=tts,
            recognition_server=SpeachesServer(http, "http://localhost:8000/v1"),
            voice_server=SpeachesServer(http, "http://localhost:8000/v1"),
            files=files,
            defaults=speech_defaults,
        )
        manageable = []
        for _ in range(3):
            models = await service.models()
            manageable.append((models.recognition_manageable, models.voice_manageable))

    assert manageable == [(False, False), (True, True), (True, True)]
    assert len(registry) == 4  # one failed and one good answer per kind's server


async def test_save_reports_a_server_that_does_not_answer(
    service: SpeechService,
    speech_defaults: SpeechSettings,
    recognition: FakeServer,
    voice_server: FakeServer,
) -> None:
    recognition.error = voice_server.error = UNREACHABLE

    with pytest.raises(SpeechSettingsError) as refused:
        await service.save(speech_defaults.model_copy(update={"stt_model": SMALL}))

    assert refused.value.status == 502
    assert UNREACHABLE.message in refused.value.message
    # The defaults need no check (they are always installed): the speed and the turn still save.
    saved = await service.save(speech_defaults.model_copy(update={"max_turn_s": 300}))
    assert (saved.max_turn_s, saved.source) == (300, "saved")


async def test_for_session_keeps_the_choice_when_the_server_does_not_answer(
    service: SpeechService,
    speech_defaults: SpeechSettings,
    installed: set[str],
    recognition: FakeServer,
    voice_server: FakeServer,
) -> None:
    installed.add(SMALL)
    await service.save(speech_defaults.model_copy(update={"stt_model": SMALL}))
    recognition.error = voice_server.error = UNREACHABLE

    session = await service.for_session()

    assert (session.stt_model, session.missing) == (SMALL, ())
    assert (await service.view()).missing == []


async def test_voices_come_from_the_server_and_are_checked_only_when_listed(
    service: SpeechService,
    speech_defaults: SpeechSettings,
    installed: set[str],
    voice_server: FakeServer,
) -> None:
    assert await service.voices(KOKORO) == [HEART, EMMA]

    installed.add(KOKORO_INT8)
    voice_server.voices_of[KOKORO_INT8] = []
    saved = await service.save(
        speech_defaults.model_copy(update={"tts_model": KOKORO_INT8, "tts_voice": "my_voice"})
    )
    assert saved.tts_voice == "my_voice"

    voice_server.error = UNREACHABLE
    assert await service.voices(KOKORO) == []


async def test_downloading_an_installed_model_just_selects_it(
    service: SpeechService, installed: set[str], files: FakeFiles
) -> None:
    installed.update({ALBA, TINY})

    await service.download("piper-alba", activate=False)
    assert (await service.view()).tts_model == KOKORO  # nothing to do

    await service.download("piper-alba", activate=True)
    view = await service.view()
    assert (view.tts_model, view.tts_voice) == (ALBA, "alba")
    assert files.task is None  # nothing was downloaded

    await service.download("whisper-small-en", activate=True)
    await service.download("whisper-tiny-en", activate=True)  # installed: chosen, not a 409
    view = await service.view()
    assert (view.stt_model, view.pending) == (TINY, [])


async def test_a_half_written_model_is_not_installed(
    service: SpeechService, speech_defaults: SpeechSettings, installed: set[str], files: FakeFiles
) -> None:
    """A hard kill mid-download and a quick restart: Speaches lists the folder, but the files
    are not all there, so the model can be downloaded again and not chosen meanwhile."""
    installed.add(SMALL)
    files.partial.add(SMALL)

    assert _row(await service.models(), SMALL).state == "available"
    with pytest.raises(SpeechSettingsError) as refused:
        await service.save(speech_defaults.model_copy(update={"stt_model": SMALL}))
    assert refused.value.status == 422

    await service.download("whisper-small-en", activate=True)  # not "just select it"
    await files.finish()

    assert _row(await service.models(), SMALL).state == "installed"
    assert (await service.view()).stt_model == SMALL


async def test_preview_reports_a_voice_server_that_fails(
    service: SpeechService, tts: NonCallableMagicMock
) -> None:
    tts.synthesize.side_effect = lambda _text, _voice: _failing_stream()

    with pytest.raises(SpeechSettingsError) as refused:
        await service.preview(VoicePreview(model=KOKORO, voice="af_heart", speed=1.0))

    assert (refused.value.status, refused.value.message) == (502, UNREACHABLE.message)


async def test_synthesize_streams_the_tutors_voice(
    service: SpeechService, tts: NonCallableMagicMock
) -> None:
    tts.synthesize.side_effect = lambda _text, _voice: _stream(b"\x01\x00", b"\x02\x00")
    voice = VoiceChoice(KOKORO, "af_heart", 1.0)

    assert [chunk async for chunk in service.synthesize("Hi.", voice)] == [
        b"\x01\x00",
        b"\x02\x00",
    ]
    tts.synthesize.assert_called_once_with("Hi.", voice)


async def test_status_is_of_the_models_in_use(
    service: SpeechService,
    speech_defaults: SpeechSettings,
    installed: set[str],
    stt: NonCallableMagicMock,
    tts: NonCallableMagicMock,
) -> None:
    def ready(model: str) -> ModelStatus:
        return ModelStatus(
            base_url="http://localhost:8000/v1", model=model, reachable=True, model_ready=True
        )

    stt.status.side_effect = ready
    tts.status.side_effect = ready
    installed.update({SMALL, ALBA})
    await service.save(
        speech_defaults.model_copy(
            update={"stt_model": SMALL, "tts_model": ALBA, "tts_voice": "alba"}
        )
    )

    status = await service.status()
    assert (status.recognition.model, status.synthesis.model) == (SMALL, ALBA)

    installed.discard(SMALL)  # a voice turn falls back to the default: so does the status
    status = await service.status()
    assert (status.recognition.model, status.synthesis.model) == (WHISPER, ALBA)


async def test_aclose_cancels_a_running_download(service: SpeechService, files: FakeFiles) -> None:
    await service.download("whisper-small-en", activate=True)
    task = await files.started()

    await service.aclose()

    assert task.cancelled()


async def test_a_configured_default_outside_the_list_is_shown(
    database: Database,
    speech_defaults: SpeechSettings,
    installed: set[str],
    recognition: FakeServer,
    voice_server: FakeServer,
    files: FakeFiles,
    stt: NonCallableMagicMock,
    tts: NonCallableMagicMock,
) -> None:
    installed.add("acme/whisper-custom.en")
    service = SpeechService(
        repository=SqlSpeechSettingsRepository(database),
        stt=stt,
        tts=tts,
        recognition_server=recognition,
        voice_server=voice_server,
        files=files,
        defaults=speech_defaults.model_copy(update={"stt_model": "acme/whisper-custom.en"}),
    )

    row = _row(await service.models(), "acme/whisper-custom.en")

    assert (row.key, row.state, row.from_configuration) == (
        "configured-whisper-custom-en",
        "installed",
        True,
    )
    assert (row.default, row.selected) == (True, True)
    with pytest.raises(SpeechSettingsError) as refused:
        await service.uninstall(row.key)
    assert refused.value.status == 409


async def test_the_default_longest_turn_is_known_before_any_session(
    speech_defaults: SpeechSettings, service: SpeechService
) -> None:
    assert service.default_max_turn_s == speech_defaults.max_turn_s
