"""`SpeechService` over in-memory fakes of Speaches and the models folder, with the real settings
table."""

import asyncio
import io
import itertools
import wave
from collections.abc import AsyncIterator, Callable, Collection, Iterator
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
    GpuProblem,
    Recognition,
    SessionSpeech,
    SpeechSettingsError,
    VoiceChoice,
    transcription_timeout_s,
)
from vt_api.services.speech import PREVIEW_TEXT, SpeechService
from vt_contracts.speech import (
    DownloadProgress,
    ModelStatus,
    SpeechEngineState,
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
SMALL_Q8 = "ggerganov/whisper.cpp/ggml-small.en-q8_0.bin"  # the GPU default
MEDIUM_Q5 = "ggerganov/whisper.cpp/ggml-medium.en-q5_0.bin"
TURBO_Q5 = "ggerganov/whisper.cpp/ggml-large-v3-turbo-q5_0.bin"
SMALL_Q8_PATH = f"snapshots/{SMALL_Q8}"  # where `FakeFiles` has it
ON_SPEACHES = Recognition("openai", WHISPER, WHISPER)
ON_THE_GPU = Recognition("whispercpp", SMALL_Q8, SMALL_Q8_PATH)
GPU_KEYS = [
    "whispercpp-base-en",
    "whispercpp-small-en-q8",
    "whispercpp-medium-en-q5",
    "whispercpp-large-v3-turbo-q5",
    "whispercpp-large-v3-turbo-q8",
    "whispercpp-large-v3-turbo",
]
GPU_STOPPED = (
    "whisper.cpp (GPU) is not running: start it with `just voice gpu` (Linux, AMD or Intel GPU)."
)

HEART = Voice(id="af_heart", name="Heart", accent="american", gender="female")
EMMA = Voice(id="bf_emma", name="Emma", accent="british", gender="female")
ALBA_VOICE = Voice(id="alba", name="Alba", accent="british", gender="female")
UNREACHABLE = ProviderError("connection", "Could not connect to http://localhost:8000.")
LOAD_FAILED = ProviderError("connection", "Could not connect to http://localhost:8002/v1.")


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

    async def present(self, model_ids: Collection[str]) -> set[str]:
        return {model_id for model_id in model_ids if model_id in self.models}

    async def snapshot_path(self, model_id: str) -> str | None:
        return f"snapshots/{model_id}" if model_id in self.models else None

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


class FakeGpu:
    """The whisper.cpp server; `up` is whether it answers."""

    def __init__(self) -> None:
        self.up = True
        self.loaded: list[str] = []
        """The model paths `load` was asked for, in order."""
        self.load_error: ProviderError | None = None
        """Raised by `load`: the file did not load (the server exits, dropping the connection)."""
        self.text = "Hello from the GPU"
        self.asked: list[tuple[str, float]] = []
        """The model path and timeout of each transcription."""

    async def running(self) -> bool:
        await asyncio.sleep(0)  # an HTTP call: other requests run meanwhile
        return self.up

    async def load(self, model: str) -> None:
        self.loaded.append(model)
        if self.load_error is not None:
            raise self.load_error

    async def transcribe(self, wav: bytes, model: str, timeout_s: float) -> str:
        self.asked.append((model, timeout_s))
        return self.text

    async def status(self, model: str) -> ModelStatus:
        return ModelStatus(
            base_url="http://localhost:8002/v1", model=model, reachable=self.up, model_ready=self.up
        )


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
def gpu() -> FakeGpu:
    return FakeGpu()


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
def build(
    database: Database,
    speech_defaults: SpeechSettings,
    recognition: FakeServer,
    voice_server: FakeServer,
    files: FakeFiles,
    gpu: FakeGpu,
    stt: NonCallableMagicMock,
    tts: NonCallableMagicMock,
    clock: Clock,
) -> Callable[..., SpeechService]:
    """A `SpeechService` over the fakes, with `changes` to its arguments."""

    def build(**changes: Any) -> SpeechService:
        arguments: dict[str, Any] = {
            "repository": SqlSpeechSettingsRepository(database),
            "stt": stt,
            "tts": tts,
            "recognition_server": recognition,
            "voice_server": voice_server,
            "files": files,
            "defaults": speech_defaults,
            "gpu_stt": gpu,
            "clock": clock,
        }
        return SpeechService(**(arguments | changes))

    return build


@pytest.fixture
async def service(build: Callable[..., SpeechService]) -> AsyncIterator[SpeechService]:
    service = build()
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
    await service.transcribe(b"wav", 2.0, ON_SPEACHES)
    await service.transcribe(b"wav", 4.0, ON_SPEACHES)

    models = await service.models()

    assert _row(models, TINY) == SpeechModel(
        key="whisper-tiny-en",
        kind="recognition",
        engine="openai",
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
    assert [(m.kind, m.engine, m.model_id) for m in models.models if m.selected] == [
        ("recognition", "openai", WHISPER),
        ("recognition", "whispercpp", SMALL_Q8),
        ("voice", "openai", KOKORO),
    ]
    assert [m.model_id for m in models.models if m.default] == [WHISPER, SMALL_Q8, KOKORO]
    assert len(models.models) == 20
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
            stt_model=SMALL,
            stt_engine="openai",
            stt_gpu_model=SMALL_Q8,
            tts_model=ALBA,
            tts_voice="alba",
            tts_speed=1.1,
            max_turn_s=180,
        )
    )
    assert await service.for_session() == SessionSpeech(
        Recognition("openai", SMALL, SMALL), VoiceChoice(ALBA, "alba", 1.1, 24_000), 180
    )

    installed.difference_update({SMALL, ALBA})  # removed with Speaches' own tools

    assert await service.for_session() == SessionSpeech(
        ON_SPEACHES, VoiceChoice(KOKORO, "af_heart", 1.1), 180, missing=("recognition", "voice")
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

    assert await service.transcribe(b"wav", 90.0, Recognition("openai", SMALL, SMALL)) == (
        "Hello there"
    )

    stt.transcribe.assert_awaited_once_with(b"wav", SMALL, transcription_timeout_s(90.0))


async def test_a_failed_transcription_is_not_measured(
    service: SpeechService, stt: NonCallableMagicMock
) -> None:
    stt.transcribe.side_effect = UNREACHABLE

    with pytest.raises(ProviderError):
        await service.transcribe(b"wav", 2.0, ON_SPEACHES)

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
    assert models.engines[0] == SpeechEngineState(engine="openai", running=False, manageable=False)
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

    assert (session.recognition.model, session.missing) == (SMALL, ())
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
    assert status.recognition_engine == "openai"

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


# ---------------------------------------------------------------- engines and GPU models


@pytest.mark.parametrize("up", [True, False])
async def test_models_list_the_gpu_models_and_the_engines(
    service: SpeechService,
    speech_defaults: SpeechSettings,
    installed: set[str],
    gpu: FakeGpu,
    up: bool,
) -> None:
    installed.update({SMALL_Q8, TURBO_Q5})
    await service.save(speech_defaults.model_copy(update={"stt_gpu_model": TURBO_Q5}))
    gpu.up = up

    models = await service.models()

    rows = [m for m in models.models if m.engine == "whispercpp"]
    assert [m.key for m in rows] == GPU_KEYS
    assert {m.kind for m in rows} == {"recognition"}
    assert [m.model_id for m in rows if m.state == "installed"] == [SMALL_Q8, TURBO_Q5]
    assert [m.model_id for m in rows if m.selected] == [TURBO_Q5]
    assert [m.model_id for m in rows if m.default] == [SMALL_Q8]
    assert _row(models, TURBO_Q5) == SpeechModel(
        key=GPU_KEYS[3],  # whispercpp-large-v3-turbo-q5
        kind="recognition",
        engine="whispercpp",
        model_id=TURBO_Q5,
        label="Whisper large v3 turbo (5-bit)",
        hint="The accurate choice (multilingual)",
        approx_mb=574,
        english_only=False,
        state="installed",
        download=None,
        default=False,
        selected=True,
        from_configuration=False,
        ms_per_audio_s=None,
    )
    assert {m.engine for m in models.models if m.key not in GPU_KEYS} == {"openai"}
    assert models.engines == [
        SpeechEngineState(engine="openai", running=True, manageable=True),
        SpeechEngineState(engine="whispercpp", running=up, manageable=True),
    ]


@pytest.mark.parametrize("missing", ["files", "gpu_stt"])
async def test_the_gpu_engine_needs_the_models_folder_and_its_server(
    build: Callable[..., SpeechService], installed: set[str], missing: str
) -> None:
    """Without the models folder the api cannot find the GPU files, so nothing on it counts as
    installed. Either way the engine is not usable (only tests leave the GPU server out)."""
    installed.add(TURBO_Q5)
    service = build(**{missing: None})

    models = await service.models()

    assert models.engines[1] == SpeechEngineState(
        engine="whispercpp", running=False, manageable=False
    )
    expected = "available" if missing == "files" else "installed"
    assert _row(models, TURBO_Q5).state == expected


async def test_switching_to_a_stopped_engine_is_refused(
    service: SpeechService, speech_defaults: SpeechSettings, gpu: FakeGpu
) -> None:
    gpu.up = False

    with pytest.raises(SpeechSettingsError) as refused:
        await service.save(speech_defaults.model_copy(update={"stt_engine": "whispercpp"}))

    assert (refused.value.status, refused.value.message) == (409, GPU_STOPPED)
    assert (await service.view()).source == "environment"


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        (
            "files",
            "whisper.cpp (GPU) needs VT_SPEECH_MODELS_DIR, the models folder it shares with the "
            "api (see docs/configuration.md).",
        ),
        ("gpu_stt", GPU_STOPPED),
    ],
)
async def test_switching_to_an_unusable_gpu_engine_is_refused(
    build: Callable[..., SpeechService],
    speech_defaults: SpeechSettings,
    missing: str,
    message: str,
) -> None:
    service = build(**{missing: None})

    with pytest.raises(SpeechSettingsError) as refused:
        await service.save(speech_defaults.model_copy(update={"stt_engine": "whispercpp"}))

    assert (refused.value.status, refused.value.message) == (409, message)


async def test_switching_back_to_a_stopped_speaches_is_refused(
    service: SpeechService, speech_defaults: SpeechSettings, recognition: FakeServer
) -> None:
    gpu_settings = speech_defaults.model_copy(update={"stt_engine": "whispercpp"})
    await service.save(gpu_settings)
    recognition.error = UNREACHABLE

    with pytest.raises(SpeechSettingsError) as refused:
        await service.save(speech_defaults)

    assert (refused.value.status, refused.value.message) == (
        409,
        "Speaches is not running: start it with `just voice`.",
    )
    assert (await service.view()).stt_engine == "whispercpp"


async def test_switching_to_a_running_engine_saves(
    service: SpeechService, speech_defaults: SpeechSettings
) -> None:
    saved = await service.save(speech_defaults.model_copy(update={"stt_engine": "whispercpp"}))

    assert (saved.stt_engine, saved.stt_model, saved.stt_gpu_model, saved.source) == (
        "whispercpp",
        WHISPER,
        SMALL_Q8,
        "saved",
    )
    assert (await service.view()).stt_engine == "whispercpp"

    saved = await service.save(speech_defaults)  # back to Speaches, which answers
    assert (saved.stt_engine, saved.source) == ("openai", "saved")


async def test_a_gpu_model_must_be_installed(
    service: SpeechService,
    build: Callable[..., SpeechService],
    speech_defaults: SpeechSettings,
    installed: set[str],
) -> None:
    installed.add(SMALL)  # on Speaches, but not a whisper.cpp file
    refusals: list[tuple[int, str]] = []

    for model in (MEDIUM_Q5, SMALL):
        with pytest.raises(SpeechSettingsError) as refused:
            await service.save(speech_defaults.model_copy(update={"stt_gpu_model": model}))
        refusals.append((refused.value.status, refused.value.message))

    assert refusals == [
        (422, f"{MEDIUM_Q5} is not installed: download it first."),
        (422, f"{SMALL} is not a speech recognition model for whisper.cpp."),
    ]
    installed.add(MEDIUM_Q5)
    saved = await service.save(speech_defaults.model_copy(update={"stt_gpu_model": MEDIUM_Q5}))
    assert (saved.stt_gpu_model, saved.stt_model) == (MEDIUM_Q5, WHISPER)
    # The default is always accepted, as `just voice gpu` downloads it before the server starts.
    saved = await service.save(speech_defaults)
    assert saved.stt_gpu_model == SMALL_Q8
    # Without the models folder, no GPU file can be found.
    with pytest.raises(SpeechSettingsError) as refused:
        await build(files=None).save(
            speech_defaults.model_copy(update={"stt_gpu_model": MEDIUM_Q5})
        )
    assert refused.value.status == 422


async def test_only_a_changed_engine_is_checked(
    service: SpeechService, speech_defaults: SpeechSettings, gpu: FakeGpu
) -> None:
    """Review Focus 4: the saved engine stopped, and the learner changes something else."""
    chosen = speech_defaults.model_copy(update={"stt_engine": "whispercpp"})
    await service.save(chosen)
    gpu.up = False

    saved = await service.save(chosen.model_copy(update={"tts_speed": 1.2}))

    assert (saved.stt_engine, saved.tts_speed) == ("whispercpp", 1.2)
    view = await service.view()
    assert (view.stt_engine, view.stt_model, view.missing) == ("whispercpp", WHISPER, [])
    assert (await service.models()).engines[1].running is False


BASE_EN = "ggerganov/whisper.cpp/ggml-base.en.bin"


async def test_a_row_saved_before_the_gpu_engine_uses_the_configured_gpu_model(
    build: Callable[..., SpeechService],
    database: Database,
    speech_defaults: SpeechSettings,
    installed: set[str],
) -> None:
    """Migration 0003 leaves a row saved before it with no GPU choice (`""`): wherever the
    saved settings are read, the configured default (`VT_STT_GPU_MODEL`) stands in."""
    installed.add(BASE_EN)
    service = build(defaults=speech_defaults.model_copy(update={"stt_gpu_model": BASE_EN}))
    await SqlSpeechSettingsRepository(database).save(
        speech_defaults.model_copy(update={"stt_gpu_model": "", "tts_speed": 1.1})
    )

    view = await service.view()
    assert (view.stt_gpu_model, view.tts_speed, view.source, view.missing) == (
        BASE_EN,
        1.1,
        "saved",
        [],
    )
    assert [m.model_id for m in (await service.models()).models if m.selected] == [
        WHISPER,
        BASE_EN,
        KOKORO,
    ]

    shown = SpeechSettings.model_validate(view.model_dump(exclude={"source", "missing", "pending"}))
    saved = await service.save(shown.model_copy(update={"tts_speed": 1.2}))  # as the UI does

    assert (saved.stt_gpu_model, saved.tts_speed) == (BASE_EN, 1.2)


async def test_a_conversation_on_a_row_without_a_gpu_choice_uses_the_configured_model(
    build: Callable[..., SpeechService],
    database: Database,
    speech_defaults: SpeechSettings,
    installed: set[str],
    gpu: FakeGpu,
) -> None:
    installed.add(BASE_EN)
    service = build(defaults=speech_defaults.model_copy(update={"stt_gpu_model": BASE_EN}))
    await SqlSpeechSettingsRepository(database).save(
        speech_defaults.model_copy(update={"stt_engine": "whispercpp", "stt_gpu_model": ""})
    )

    session = await service.for_session()

    assert session.recognition == Recognition("whispercpp", BASE_EN, f"snapshots/{BASE_EN}")
    assert session.missing == ()  # nothing was chosen, so nothing is missing


async def test_choosing_an_installed_gpu_model_keeps_the_speaches_one(
    service: SpeechService, installed: set[str]
) -> None:
    installed.add(MEDIUM_Q5)

    await service.download("whispercpp-medium-en-q5", activate=True)

    view = await service.view()
    assert (view.stt_gpu_model, view.stt_model) == (MEDIUM_Q5, WHISPER)


async def test_download_a_gpu_model_and_use_it(
    service: SpeechService, files: FakeFiles, installed: set[str]
) -> None:
    """The GPU server never lists its models, so no Speaches check applies to them."""
    started = await service.download("whispercpp-medium-en-q5", activate=True)

    assert _row(started, MEDIUM_Q5).state == "downloading"
    assert (await service.view()).pending == [MEDIUM_Q5]
    await files.finish()

    view = await service.view()
    assert (view.stt_gpu_model, view.stt_model, view.pending) == (MEDIUM_Q5, WHISPER, [])
    assert (await service.models()).last_error is None
    assert MEDIUM_Q5 in installed


async def test_gpu_download_without_activate_leaves_the_choice(
    service: SpeechService, files: FakeFiles
) -> None:
    await service.download("whispercpp-medium-en-q5", activate=False)
    await files.finish()

    view = await service.view()
    assert (view.stt_gpu_model, view.stt_model) == (SMALL_Q8, WHISPER)
    assert _row(await service.models(), MEDIUM_Q5).state == "installed"


async def test_cancel_a_gpu_download(service: SpeechService, files: FakeFiles) -> None:
    await service.download("whispercpp-medium-en-q5", activate=True)
    await files.started()

    await service.cancel_download("whispercpp-medium-en-q5")

    models = await service.models()
    assert _row(models, MEDIUM_Q5).state == "available"
    assert (await service.view()).stt_gpu_model == SMALL_Q8


@pytest.mark.parametrize("missing", ["files", "gpu_stt"])
async def test_gpu_models_need_the_models_folder(
    build: Callable[..., SpeechService], missing: str
) -> None:
    service = build(**{missing: None})

    with pytest.raises(SpeechSettingsError) as refused:
        await service.download("whispercpp-medium-en-q5", activate=True)

    assert refused.value.status == 409
    assert refused.value.message == (
        "Models for whisper.cpp (GPU) can be downloaded and uninstalled only with "
        "VT_SPEECH_MODELS_DIR set (see docs/configuration.md)."
    )
    assert (await service.models()).engines[1].manageable is False


async def test_gpu_models_are_manageable_while_the_gpu_server_is_stopped(
    service: SpeechService, gpu: FakeGpu, files: FakeFiles
) -> None:
    gpu.up = False

    models = await service.models()
    await service.download("whispercpp-medium-en-q5", activate=False)

    assert models.engines[1] == SpeechEngineState(
        engine="whispercpp", running=False, manageable=True
    )
    await files.finish()


async def test_uninstall_a_gpu_model(
    service: SpeechService,
    speech_defaults: SpeechSettings,
    installed: set[str],
    files: FakeFiles,
    calls: list[str],
    recognition: FakeServer,
) -> None:
    installed |= {MEDIUM_Q5, TURBO_Q5}
    await service.save(speech_defaults.model_copy(update={"stt_gpu_model": TURBO_Q5}))
    await service.download("whispercpp-base-en", activate=False)
    refusals: dict[str, str] = {}

    for key in ("whispercpp-small-en-q8", "whispercpp-large-v3-turbo-q5", "whispercpp-base-en"):
        with pytest.raises(SpeechSettingsError) as refused:
            await service.uninstall(key)
        assert refused.value.status == 409
        refusals[key] = refused.value.message

    assert "is the default and stays installed." in refusals["whispercpp-small-en-q8"]
    assert "is in use: choose another model first." in refusals["whispercpp-large-v3-turbo-q5"]
    assert "cancel the download first" in refusals["whispercpp-base-en"]
    assert calls == []

    await service.uninstall("whispercpp-medium-en-q5")

    assert calls == [f"delete {MEDIUM_Q5}"]  # no `unload`: Speaches never loaded it
    await files.finish()


async def test_uninstall_a_gpu_model_without_the_models_folder(
    build: Callable[..., SpeechService],
) -> None:
    with pytest.raises(SpeechSettingsError) as refused:
        await build(files=None).uninstall("whispercpp-medium-en-q5")

    assert refused.value.status == 409
    assert "only with VT_SPEECH_MODELS_DIR set" in refused.value.message


async def test_choosing_a_speaches_model_does_not_touch_the_gpu_choice(
    service: SpeechService, speech_defaults: SpeechSettings, installed: set[str]
) -> None:
    installed |= {SMALL, MEDIUM_Q5}
    await service.save(speech_defaults.model_copy(update={"stt_gpu_model": MEDIUM_Q5}))

    await service.download("whisper-small-en", activate=True)

    view = await service.view()
    assert (view.stt_model, view.stt_gpu_model) == (SMALL, MEDIUM_Q5)


async def test_a_gpu_model_cannot_be_chosen_without_the_models_folder(
    build: Callable[..., SpeechService], speech_defaults: SpeechSettings
) -> None:
    """The learner cannot download it either, so say what is missing."""
    with pytest.raises(SpeechSettingsError) as refused:
        await build(files=None).save(
            speech_defaults.model_copy(update={"stt_gpu_model": MEDIUM_Q5})
        )

    assert refused.value.status == 422
    assert refused.value.message == (
        "whisper.cpp (GPU) needs VT_SPEECH_MODELS_DIR, the models folder it shares with the api "
        "(see docs/configuration.md)."
    )


# ---------------------------------------------------------------- conversations and engines


async def test_session_uses_the_gpu_and_loads_its_model(
    service: SpeechService, speech_defaults: SpeechSettings, installed: set[str], gpu: FakeGpu
) -> None:
    installed.add(SMALL_Q8)
    await service.save(speech_defaults.model_copy(update={"stt_engine": "whispercpp"}))

    session = await service.for_session()

    assert session.recognition == ON_THE_GPU
    assert gpu.loaded == [SMALL_Q8_PATH]
    assert session.fallback == ON_SPEACHES
    assert (session.missing, session.gpu_problem, session.gpu_model_label) == ((), None, None)


async def test_a_speaches_session_never_asks_the_gpu(
    service: SpeechService, installed: set[str], gpu: FakeGpu
) -> None:
    installed.add(SMALL_Q8)

    session = await service.for_session()

    assert (session.recognition, session.fallback, session.gpu_problem) == (
        ON_SPEACHES,
        None,
        None,
    )
    assert gpu.loaded == []


async def test_view_and_status_do_not_load(
    service: SpeechService,
    speech_defaults: SpeechSettings,
    installed: set[str],
    gpu: FakeGpu,
    tts: NonCallableMagicMock,
) -> None:
    """Loading swaps the model in GPU memory: only a conversation that starts does it."""
    tts.status.return_value = ModelStatus(
        base_url="http://localhost:8000/v1", model=KOKORO, reachable=True, model_ready=True
    )
    installed.add(SMALL_Q8)
    chosen = speech_defaults.model_copy(update={"stt_engine": "whispercpp"})

    await service.save(chosen)
    await service.save(chosen.model_copy(update={"tts_speed": 1.2}))
    await service.view()
    await service.status()

    assert gpu.loaded == []


@pytest.mark.parametrize(
    ("cause", "problem"),
    [
        ("stopped", "stopped"),
        ("no GPU engine", "stopped"),  # only tests leave the GPU server out
        ("no models folder", "no_models_dir"),
        ("no model file", "no_model"),
    ],
)
async def test_session_says_why_the_gpu_does_not_transcribe(
    build: Callable[..., SpeechService],
    speech_defaults: SpeechSettings,
    installed: set[str],
    gpu: FakeGpu,
    cause: str,
    problem: GpuProblem,
) -> None:
    """Review Focus 2 and 4: the saved engine (here `VT_STT_BACKEND`) cannot transcribe, so
    Speaches does, and the conversation says why."""
    installed.add(SMALL_Q8)
    changes: dict[str, Any] = {
        "defaults": speech_defaults.model_copy(update={"stt_engine": "whispercpp"})
    }
    match cause:
        case "stopped":
            gpu.up = False
        case "no model file":
            installed.discard(SMALL_Q8)
        case "no models folder":
            changes["files"] = None
        case "no GPU engine":
            changes["gpu_stt"] = None
    service = build(**changes)

    session = await service.for_session()

    assert (session.recognition, session.fallback) == (ON_SPEACHES, None)
    assert (session.gpu_problem, session.gpu_model_label) == (problem, None)
    assert (session.missing, gpu.loaded) == ((), [])
    assert (await service.view()).missing == []
    await service.aclose()


async def test_session_says_no_model_when_neither_the_choice_nor_the_default_is_there(
    service: SpeechService, speech_defaults: SpeechSettings, installed: set[str], gpu: FakeGpu
) -> None:
    installed.add(MEDIUM_Q5)
    await service.save(
        speech_defaults.model_copy(update={"stt_engine": "whispercpp", "stt_gpu_model": MEDIUM_Q5})
    )
    installed.discard(MEDIUM_Q5)  # removed by hand; the default was never downloaded

    session = await service.for_session()

    assert (session.recognition, session.gpu_problem) == (ON_SPEACHES, "no_model")
    assert gpu.loaded == []


@pytest.mark.parametrize(
    "error",
    [
        LOAD_FAILED,  # the file did not load: the server exited and dropped the connection
        ProviderError("connection", "http://localhost:8002/v1 did not answer in time."),
    ],
)
async def test_session_says_which_gpu_model_did_not_load(
    service: SpeechService,
    speech_defaults: SpeechSettings,
    installed: set[str],
    gpu: FakeGpu,
    error: ProviderError,
) -> None:
    """Review Focus 3: by its catalog label, perhaps too big for the GPU's memory."""
    installed |= {SMALL_Q8, MEDIUM_Q5}
    await service.save(
        speech_defaults.model_copy(update={"stt_engine": "whispercpp", "stt_gpu_model": MEDIUM_Q5})
    )
    gpu.load_error = error

    session = await service.for_session()

    assert (session.recognition, session.fallback) == (ON_SPEACHES, None)
    assert (session.gpu_problem, session.gpu_model_label) == (
        "load_failed",
        "Whisper medium (English, 5-bit)",
    )
    assert gpu.loaded == [f"snapshots/{MEDIUM_Q5}"]
    assert (await service.for_session()).gpu_problem == "load_failed"  # each start tries again
    assert len(gpu.loaded) == 2


async def test_a_configured_gpu_model_that_did_not_load_is_named_by_its_id(
    build: Callable[..., SpeechService],
    speech_defaults: SpeechSettings,
    installed: set[str],
    gpu: FakeGpu,
) -> None:
    tiny = "ggerganov/whisper.cpp/ggml-tiny.en.bin"  # `VT_STT_GPU_MODEL`, not in the catalog
    installed.add(tiny)
    gpu.load_error = LOAD_FAILED
    service = build(
        defaults=speech_defaults.model_copy(
            update={"stt_engine": "whispercpp", "stt_gpu_model": tiny}
        )
    )

    session = await service.for_session()

    assert (session.gpu_problem, session.gpu_model_label) == ("load_failed", tiny)


async def test_missing_gpu_model_uses_the_gpu_default(
    service: SpeechService, speech_defaults: SpeechSettings, installed: set[str], gpu: FakeGpu
) -> None:
    installed |= {SMALL_Q8, MEDIUM_Q5}
    await service.save(
        speech_defaults.model_copy(update={"stt_engine": "whispercpp", "stt_gpu_model": MEDIUM_Q5})
    )
    installed.discard(MEDIUM_Q5)  # removed by hand

    session = await service.for_session()

    assert (session.recognition, session.missing) == (ON_THE_GPU, ("recognition",))
    assert gpu.loaded == [SMALL_Q8_PATH]
    view = await service.view()
    assert (view.stt_gpu_model, view.missing) == (MEDIUM_Q5, ["recognition"])


async def test_the_chosen_gpu_model_is_used_when_present(
    service: SpeechService, speech_defaults: SpeechSettings, installed: set[str], gpu: FakeGpu
) -> None:
    installed |= {SMALL_Q8, MEDIUM_Q5}
    await service.save(
        speech_defaults.model_copy(update={"stt_engine": "whispercpp", "stt_gpu_model": MEDIUM_Q5})
    )

    session = await service.for_session()

    assert session.recognition == Recognition("whispercpp", MEDIUM_Q5, f"snapshots/{MEDIUM_Q5}")
    assert (gpu.loaded, session.missing) == ([f"snapshots/{MEDIUM_Q5}"], ())


async def test_transcribe_with_the_gpu_records_its_speed(
    service: SpeechService, gpu: FakeGpu, stt: NonCallableMagicMock, clock: Clock
) -> None:
    clock.readings = iter([0.0, 0.5])  # 500 ms

    assert await service.transcribe(b"wav", 2.0, ON_THE_GPU) == "Hello from the GPU"

    assert gpu.asked == [(SMALL_Q8_PATH, transcription_timeout_s(2.0))]
    stt.transcribe.assert_not_awaited()
    models = await service.models()
    assert _row(models, SMALL_Q8).ms_per_audio_s == 250.0  # keyed by the model id, not the path
    assert _row(models, WHISPER).ms_per_audio_s is None


async def test_status_reports_the_engine_in_use(
    service: SpeechService,
    speech_defaults: SpeechSettings,
    installed: set[str],
    gpu: FakeGpu,
    stt: NonCallableMagicMock,
    tts: NonCallableMagicMock,
) -> None:
    def ready(model: str) -> ModelStatus:
        return ModelStatus(
            base_url="http://localhost:8000/v1", model=model, reachable=True, model_ready=True
        )

    stt.status.side_effect = ready
    tts.status.side_effect = ready
    installed.add(SMALL_Q8)
    await service.save(speech_defaults.model_copy(update={"stt_engine": "whispercpp"}))

    status = await service.status()
    assert (status.recognition_engine, status.recognition.model) == ("whispercpp", SMALL_Q8)
    assert status.recognition.base_url == "http://localhost:8002/v1"  # the GPU server's

    gpu.up = False  # a conversation would fall back to Speaches: so does the status
    status = await service.status()
    assert (status.recognition_engine, status.recognition.model) == ("openai", WHISPER)
    assert status.synthesis.model == KOKORO
