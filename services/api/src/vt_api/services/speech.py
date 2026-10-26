"""The speech choices saved from the UI (defaults from `VT_STT_*`, `VT_TTS_*` and
`VT_MAX_TURN_S`), model downloads, and the choice each conversation uses.

The learner chooses one model on each *track*: speech recognition on Speaches, speech recognition
on whisper.cpp (GPU), and the voice; `stt_engine` says which recognition engine to use. Models are
downloaded and uninstalled only where a track is *manageable*: Speaches or whisper.cpp (GPU), with
`VT_SPEECH_MODELS_DIR` set. Any other OpenAI-compatible server keeps working, with read-only
lists.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Literal

from vt_api.domain.audio import to_wav
from vt_api.domain.llm import ProviderError
from vt_api.domain.speech import (
    CatalogEntry,
    GpuProblem,
    Recognition,
    SessionSpeech,
    SpeechSettingsError,
    VoiceChoice,
    catalog,
    entry_for,
    transcription_timeout_s,
)
from vt_api.ports.speech import (
    GpuSpeechToText,
    ModelFiles,
    SpeechModelServer,
    SpeechSettingsRepository,
    SpeechToText,
    TextToSpeech,
)
from vt_contracts.audio import OUTPUT_SAMPLE_RATE_HZ
from vt_contracts.speech import (
    SpeechEngineState,
    SpeechKind,
    SpeechModel,
    SpeechModels,
    SpeechSettings,
    SpeechSettingsView,
    SpeechStatus,
    SttEngine,
    Voice,
    VoicePreview,
)

logger = logging.getLogger(__name__)

PREVIEW_TEXT = "Hi! I'm your English tutor. Shall we practise together?"
_NOT_SEEN_BY_SPEACHES = (
    "Downloaded, but Speaches does not see it: VT_SPEECH_MODELS_DIR must be the folder Speaches "
    "reads (see docs/configuration.md)"
)
type _Track = tuple[SpeechKind, SttEngine]
"""A list of models the learner chooses one from."""
_SPEACHES: _Track = ("recognition", "openai")
_GPU: _Track = ("recognition", "whispercpp")
_VOICE: _Track = ("voice", "openai")
_TRACKS: tuple[_Track, ...] = (_SPEACHES, _GPU, _VOICE)
_FIELDS: dict[_Track, Literal["stt_model", "stt_gpu_model", "tts_model"]] = {
    _SPEACHES: "stt_model",
    _GPU: "stt_gpu_model",
    _VOICE: "tts_model",
}
"""The setting that holds each track's model: each engine keeps its own choice."""


@dataclass(frozen=True, slots=True)
class _Wording:
    """How messages name a track's models."""

    models_of: str
    """"Models for ..." """
    one_of: str
    """"... is not <one_of>." """


_WORDING: dict[_Track, _Wording] = {
    _SPEACHES: _Wording("speech recognition", "a speech recognition model"),
    _GPU: _Wording("whisper.cpp (GPU)", "a speech recognition model for whisper.cpp"),
    _VOICE: _Wording("voice", "a voice model"),
}
_NOT_RUNNING: dict[SttEngine, str] = {
    "openai": "Speaches is not running: start it with `just voice`.",
    "whispercpp": (
        "whisper.cpp (GPU) is not running: start it with `just voice gpu` (Linux, AMD or Intel "
        "GPU)."
    ),
}
_GPU_NEEDS_FILES = (
    "whisper.cpp (GPU) needs VT_SPEECH_MODELS_DIR, the models folder it shares with the api (see "
    "docs/configuration.md)."
)


@dataclass
class _Download:
    """The one download in progress. It is over once `task` is done, however it ended."""

    entry: CatalogEntry
    activate: bool
    """Make the model the active choice when the download ends."""
    task: asyncio.Task[None] = field(init=False)


@dataclass
class _Measured:
    """Transcriptions by one model since the api started."""

    audio_s: float = 0.0
    ms: float = 0.0


@dataclass(frozen=True, slots=True)
class _OnTheGpu:
    """What `_on_the_gpu` found: the GPU recognition, or why whisper.cpp, the chosen engine,
    cannot transcribe. Neither when Speaches is the chosen engine."""

    recognition: Recognition | None = None
    problem: GpuProblem | None = None
    model_label: str | None = None
    """With `load_failed`: the model that did not load."""


@dataclass(frozen=True, slots=True)
class _TrackModels:
    """One track's catalog, with each model's state."""

    rows: list[SpeechModel]
    manageable: bool
    """Its models can be downloaded and uninstalled: `_files_for` gives the files."""
    answered: bool
    """Its server said what is installed: Speaches is running. Always, on the GPU track, whose
    files the api reads itself; whether its server runs is `_gpu_running`."""


class SpeechService:
    def __init__(
        self,
        *,
        repository: SpeechSettingsRepository,
        stt: SpeechToText,
        tts: TextToSpeech,
        recognition_server: SpeechModelServer,
        voice_server: SpeechModelServer,
        files: ModelFiles | None,
        defaults: SpeechSettings,
        gpu_stt: GpuSpeechToText | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._repository = repository
        self._stt = stt
        self._tts = tts
        self._servers: dict[SpeechKind, SpeechModelServer] = {
            "recognition": recognition_server,
            "voice": voice_server,
        }
        self._files = files
        self._gpu_stt = gpu_stt
        self._defaults = defaults
        self._clock = clock
        self._download: _Download | None = None
        self._settings_lock = asyncio.Lock()
        """Held across each read-modify-write of the saved settings, so none overwrites another."""
        self._last_error: str | None = None
        self._measured: dict[str, _Measured] = {}

    @property
    def default_max_turn_s(self) -> int:
        """The longest turn before a conversation has started and read its settings."""
        return self._defaults.max_turn_s

    async def view(self) -> SpeechSettingsView:
        saved = await self._repository.load()
        settings = saved or self._defaults
        missing = (await self._session(settings, load=False)).missing
        return self._view(settings, saved=saved is not None, missing=missing)

    async def save(self, settings: SpeechSettings) -> SpeechSettingsView:
        """Checks only what changed, so a saved model that went missing, or a server that does
        not answer, never blocks the speed or the turn length.

        Raises `SpeechSettingsError`: 409 when switching to an engine that is not running, 422
        for a model that is not installed or a voice the model does not have, 502 when the
        server cannot tell what is installed."""
        async with self._settings_lock:
            current = await self._settings()
            for track in _TRACKS:
                if _model(settings, track) != _model(current, track):
                    await self._check_installed(track, _model(settings, track))
            if settings.stt_engine != current.stt_engine:
                await self._check_engine(settings.stt_engine)
            if (settings.tts_model, settings.tts_voice) != (current.tts_model, current.tts_voice):
                voices = {voice.id for voice in await self.voices(settings.tts_model)}
                if voices and settings.tts_voice not in voices:
                    raise SpeechSettingsError(
                        422, f"{settings.tts_model} has no voice {settings.tts_voice!r}."
                    )
            await self._store(settings, current)
        missing = (await self._session(settings, load=False)).missing
        return self._view(settings, saved=True, missing=missing)

    async def models(self) -> SpeechModels:
        settings = await self._settings()
        speaches, gpu, voice, gpu_running = await asyncio.gather(
            self._track_models(_SPEACHES, settings.stt_model),
            self._track_models(_GPU, settings.stt_gpu_model),
            self._track_models(_VOICE, settings.tts_model),
            self._gpu_running(),
        )
        return SpeechModels(
            models=speaches.rows + gpu.rows + voice.rows,
            recognition_manageable=speaches.manageable,
            voice_manageable=voice.manageable,
            engines=[
                SpeechEngineState(
                    engine="openai", running=speaches.answered, manageable=speaches.manageable
                ),
                SpeechEngineState(
                    engine="whispercpp", running=gpu_running, manageable=gpu.manageable
                ),
            ],
            last_error=self._last_error,
        )

    async def download(self, key: str, activate: bool) -> SpeechModels:
        """Start downloading `key` in the background; with `activate`, it becomes the active
        choice when the download ends. An installed model is selected at once instead.

        Raises `SpeechSettingsError`: 404 for an unknown key, 409 while another model downloads
        or when this kind's models cannot be managed here.
        """
        entry = self._entry(key)
        installed = await self._is_installed(entry)
        files = await self._files_for(_track_of(entry))
        # No await from this check until the task exists, so two requests never both start one.
        running = self._running()
        if running is not None and running.entry == entry:
            running.activate = activate
        elif installed:
            if activate:
                await self._select(entry)
        elif running is not None:
            raise SpeechSettingsError(
                409, f"{running.entry.label} is downloading: wait for it, or cancel it first."
            )
        elif files is None:
            raise _unmanageable(_track_of(entry))
        else:
            download = _Download(entry, activate)
            download.task = asyncio.create_task(self._run(download, files))
            self._download = download
            self._last_error = None
        return await self.models()

    async def cancel_download(self, key: str) -> None:
        """Stop the download of `key`, if it is still running; its activation goes with it.

        Raises `SpeechSettingsError`: 404 for an unknown key, 409 while another model downloads.
        """
        entry = self._entry(key)
        running = self._running()
        if running is not None and running.entry != entry:
            raise SpeechSettingsError(
                409, f"{running.entry.label} is downloading, not {entry.label}."
            )
        await self._stop()

    async def uninstall(self, key: str) -> None:
        """Raises `SpeechSettingsError`: 404 for an unknown key; 409 for the default, the selected
        or the downloading model, or one that cannot be managed here; 500 when its files cannot be
        removed."""
        entry = self._entry(key)
        track = _track_of(entry)
        if entry.model_id == self._default(track):
            raise SpeechSettingsError(409, f"{entry.label} is the default and stays installed.")
        if entry.model_id == _model(await self._settings(), track):
            raise SpeechSettingsError(409, f"{entry.label} is in use: choose another model first.")
        running = self._running()
        if running is not None and running.entry == entry:
            raise SpeechSettingsError(
                409, f"{entry.label} is downloading: cancel the download first."
            )
        files = await self._files_for(track)
        if files is None:
            raise _unmanageable(track)
        if track != _GPU:  # the GPU server loads a file only to transcribe, and keeps none
            try:
                await self._servers[entry.kind].unload(entry.model_id)
            except ProviderError as error:  # not fatal: the files still go
                logger.warning("Could not unload %s: %s", entry.model_id, error.message)
        await files.delete(entry.model_id)

    async def voices(self, model_id: str) -> list[Voice]:
        """The English voices of a voice model; none when the server does not say."""
        try:
            return await self._servers["voice"].voices(model_id)
        except ProviderError:
            return []

    async def preview(self, request: VoicePreview) -> bytes:
        """`PREVIEW_TEXT` in the requested voice, as a WAV the browser can play. Raises
        `SpeechSettingsError` (502)."""
        voice = _voice_choice(request.model, request.voice, request.speed)
        try:
            pcm = b"".join([chunk async for chunk in self._tts.synthesize(PREVIEW_TEXT, voice)])
        except ProviderError as error:
            raise SpeechSettingsError(502, error.message) from error
        return to_wav(pcm, OUTPUT_SAMPLE_RATE_HZ)

    async def for_session(self) -> SessionSpeech:
        """The choice for a conversation that starts now. On whisper.cpp (GPU), the server
        loads the model now, so a model that does not load shows before the learner speaks."""
        return await self._session(await self._settings(), load=True)

    async def transcribe(self, wav: bytes, audio_s: float, recognition: Recognition) -> str:
        """Raises `ProviderError`, `EngineUnreachable` when the GPU server is gone. Records how
        long `recognition.model` took, for the turn-length estimate."""
        started = self._clock()
        text = await self._recognizer(recognition.engine).transcribe(
            wav, recognition.server_model, transcription_timeout_s(audio_s)
        )
        measured = self._measured.setdefault(recognition.model, _Measured())
        measured.audio_s += audio_s
        measured.ms += (self._clock() - started) * 1000
        return text

    def synthesize(self, text: str, voice: VoiceChoice) -> AsyncIterator[bytes]:
        return self._tts.synthesize(text, voice)

    async def status(self) -> SpeechStatus:
        """Whether the models a conversation would use now are ready on their servers: a saved
        model that is not installed gives way to its default, and an engine that cannot
        transcribe to Speaches, as in `for_session` (which alone loads the GPU model)."""
        session = await self._session(await self._settings(), load=False)
        used = session.recognition
        recognition, synthesis = await asyncio.gather(
            self._recognizer(used.engine).status(used.model),
            self._tts.status(session.voice.model),
        )
        return SpeechStatus(
            recognition=recognition, recognition_engine=used.engine, synthesis=synthesis
        )

    async def aclose(self) -> None:
        """Stop the download in progress, so its child process and files do not outlive us."""
        await self._stop()

    async def _settings(self) -> SpeechSettings:
        return await self._repository.load() or self._defaults

    def _view(
        self, settings: SpeechSettings, *, saved: bool, missing: tuple[SpeechKind, ...]
    ) -> SpeechSettingsView:
        running = self._running()
        return SpeechSettingsView(
            **settings.model_dump(),
            source="saved" if saved else "environment",
            missing=list(missing),
            pending=[running.entry.model_id] if running is not None and running.activate else [],
        )

    async def _session(self, settings: SpeechSettings, *, load: bool) -> SessionSpeech:
        """A saved model that is no longer installed gives way to its track's default.

        With `stt_engine` whisper.cpp, the GPU transcribes when it can (see `_on_the_gpu`), with
        Speaches as the fallback; when it cannot, Speaches does, and `gpu_problem` says why.
        `load` is for a conversation that starts: only it makes the GPU server load a model.
        """
        stt_model, tts_model, on_the_gpu = await asyncio.gather(
            self._installed_or_default(_SPEACHES, settings.stt_model),
            self._installed_or_default(_VOICE, settings.tts_model),
            self._on_the_gpu(settings, load=load),
        )
        speaches = Recognition("openai", stt_model, stt_model)
        gpu = on_the_gpu.recognition
        recognition = gpu if gpu is not None else speaches
        missing: list[SpeechKind] = []
        # Each engine keeps its own model: compare with the saved one of the engine in use.
        if recognition.model != _model(settings, ("recognition", recognition.engine)):
            missing.append("recognition")
        if tts_model != settings.tts_model:
            missing.append("voice")
        voice = settings.tts_voice if tts_model == settings.tts_model else self._defaults.tts_voice
        return SessionSpeech(
            recognition=recognition,
            voice=_voice_choice(tts_model, voice, settings.tts_speed),
            max_turn_s=settings.max_turn_s,
            missing=tuple(missing),
            fallback=speaches if gpu is not None else None,
            gpu_problem=on_the_gpu.problem,
            gpu_model_label=on_the_gpu.model_label,
        )

    async def _on_the_gpu(self, settings: SpeechSettings, *, load: bool) -> _OnTheGpu:
        """With `stt_engine` whisper.cpp, the GPU recognition when it can transcribe: the
        engine is usable (see `_gpu`), its server runs, and the models folder has the saved
        model, or else the GPU default. With `load`, the server loads it now: a `ProviderError`
        there (the file did not load, and the server exited; or it timed out) is `load_failed`.
        Each conversation start tries again: a model too big for the GPU fails each time, and
        the warning says so."""
        if settings.stt_engine != "whispercpp":
            return _OnTheGpu()
        gpu, files = self._gpu(), self._files
        if files is None:
            return _OnTheGpu(problem="no_models_dir")
        if gpu is None or not await gpu.running():
            return _OnTheGpu(problem="stopped")
        saved, default = settings.stt_gpu_model, self._default(_GPU)
        present = await files.present({saved, default})
        model = next((choice for choice in (saved, default) if choice in present), None)
        path = await files.snapshot_path(model) if model is not None else None
        if model is None or path is None:  # `path`: the file went since `present` saw it
            return _OnTheGpu(problem="no_model")
        if load:
            try:
                await gpu.load(path)
            except ProviderError as error:
                logger.warning("whisper.cpp (GPU) could not load %s: %s", model, error.message)
                entry = entry_for(model)
                label = entry.label if entry is not None else model
                return _OnTheGpu(problem="load_failed", model_label=label)
        return _OnTheGpu(recognition=Recognition("whispercpp", model, path))

    async def _installed_or_default(self, track: _Track, model_id: str) -> str:
        """`model_id`, unless the server says it is not installed (when it does not answer, a
        voice turn reports that itself)."""
        if model_id == self._default(track):
            return model_id
        try:
            installed = await self._installed(track)
        except ProviderError:
            return model_id
        return model_id if model_id in installed else self._default(track)

    async def _check_installed(self, track: _Track, model_id: str) -> None:
        # Always installed: Speaches preloads its defaults, and `just voice gpu` downloads the
        # GPU default before the server starts.
        if model_id == self._default(track):
            return
        if all(entry.model_id != model_id for entry in self._catalog(track)):
            raise SpeechSettingsError(422, f"{model_id} is not {_WORDING[track].one_of}.")
        if track == _GPU and self._files is None:  # it cannot be downloaded either
            raise SpeechSettingsError(422, _GPU_NEEDS_FILES)
        try:
            installed = await self._installed(track)
        except ProviderError as error:
            raise SpeechSettingsError(
                502, f"Could not check that {model_id} is installed: {error.message}"
            ) from error
        if model_id not in installed:
            raise SpeechSettingsError(422, f"{model_id} is not installed: download it first.")

    async def _check_engine(self, engine: SttEngine) -> None:
        """Raises `SpeechSettingsError` (409) when `engine` cannot transcribe now, with how to
        start it."""
        if engine == "whispercpp" and self._files is None:
            raise SpeechSettingsError(409, _GPU_NEEDS_FILES)
        if not await self._engine_running(engine):
            raise SpeechSettingsError(409, _NOT_RUNNING[engine])

    async def _engine_running(self, engine: SttEngine) -> bool:
        """Whether the engine's server answers: Speaches lists its models, and whisper.cpp
        answers its health check."""
        if engine == "whispercpp":
            return await self._gpu_running()
        try:
            await self._servers["recognition"].installed()
        except ProviderError:
            return False
        return True

    def _gpu(self) -> GpuSpeechToText | None:
        """The GPU engine when it is usable: it needs the models folder to find its files."""
        return self._gpu_stt if self._files is not None else None

    def _recognizer(self, engine: SttEngine) -> SpeechToText:
        """The adapter of `engine`. `_session` picks whisper.cpp only when it is usable."""
        gpu = self._gpu()
        return gpu if engine == "whispercpp" and gpu is not None else self._stt

    async def _gpu_running(self) -> bool:
        gpu = self._gpu()
        return gpu is not None and await gpu.running()

    async def _store(self, chosen: SpeechSettings, current: SpeechSettings) -> None:
        """Save `chosen`, under `_settings_lock`. Changing a track's model drops the activation
        of that track's download: the latest choice wins."""
        running = self._running()
        if running is not None:
            track = _track_of(running.entry)
            if _model(chosen, track) != _model(current, track):
                running.activate = False
        await self._repository.save(chosen)

    async def _select(self, entry: CatalogEntry, download: _Download | None = None) -> None:
        """Make an installed model the active one; for `download`, only if it still has its
        activate intent, since a choice saved meanwhile wins. A voice model keeps the current
        voice if it has it, else takes its first English voice (or keeps it when none is listed).
        """
        voices = [v.id for v in await self.voices(entry.model_id)] if entry.kind == "voice" else []
        async with self._settings_lock:  # the settings as they are now, not before the voices
            if download is not None and not download.activate:
                return
            current = await self._settings()
            chosen = current.model_copy(update={_FIELDS[_track_of(entry)]: entry.model_id})
            if voices and current.tts_voice not in voices:
                chosen = chosen.model_copy(update={"tts_voice": voices[0]})
            await self._store(chosen, current)

    async def _run(self, download: _Download, files: ModelFiles) -> None:
        """The background download. A failure ends up in `last_error`, never as an unretrieved
        task exception; a cancel ends it quietly."""
        entry = download.entry
        try:
            await files.download(entry.model_id)
            # The server itself, not `_installed()`: that leaves out the model still downloading.
            # The GPU server never lists its files: they are found in the models folder.
            if (
                _track_of(entry) != _GPU
                and entry.model_id not in await self._servers[entry.kind].installed()
            ):
                self._last_error = _NOT_SEEN_BY_SPEACHES
                try:  # nothing can use the files, so they would only take space
                    await files.delete(entry.model_id)
                except SpeechSettingsError as error:  # the error above says more
                    logger.warning("Could not remove %s: %s", entry.model_id, error.message)
            elif download.activate:
                await self._select(entry, download)
        except (SpeechSettingsError, ProviderError) as error:
            logger.warning("Downloading %s failed: %s", entry.model_id, error.message)
            self._last_error = error.message
        except Exception as error:
            logger.exception("Downloading %s failed", entry.model_id)
            self._last_error = f"Downloading {entry.model_id} failed: {error}"

    async def _stop(self) -> None:
        """Cancel our download task. `ModelFiles.download` removes the partial files as it ends."""
        running = self._running()
        if running is not None:
            if not running.task.cancelling():  # a second cancel would cut the cleanup short
                running.task.cancel()
            await asyncio.wait({running.task})

    def _running(self) -> _Download | None:
        download = self._download
        return download if download is not None and not download.task.done() else None

    async def _track_models(self, track: _Track, selected: str) -> _TrackModels:
        """The track's catalog with each model's state. A server that does not answer has
        nothing installed and cannot be managed."""
        try:
            installed = await self._installed(track)
        except ProviderError:
            installed, manageable, answered = set(), False, False
        else:
            manageable, answered = await self._files_for(track) is not None, True
        rows = [self._model_row(entry, installed, selected) for entry in self._catalog(track)]
        return _TrackModels(rows, manageable, answered)

    def _model_row(self, entry: CatalogEntry, installed: set[str], selected: str) -> SpeechModel:
        """`download` stays `None` until the files report bytes, and once they are complete."""
        running = self._running()
        downloading = running is not None and running.entry == entry
        progress = self._files.progress() if downloading and self._files is not None else None
        measured = self._measured.get(entry.model_id)
        return SpeechModel(
            key=entry.key,
            kind=entry.kind,
            engine=entry.engine,
            model_id=entry.model_id,
            label=entry.label,
            hint=entry.hint,
            approx_mb=entry.approx_mb,
            english_only=entry.english_only,
            state=(
                "downloading"
                if downloading
                else "installed"
                if entry.model_id in installed
                else "available"
            ),
            download=progress[1] if progress is not None else None,
            default=entry.model_id == self._default(_track_of(entry)),
            selected=entry.model_id == selected,
            from_configuration=entry_for(entry.model_id) is None,
            ms_per_audio_s=(
                round(measured.ms / measured.audio_s, 1)
                if measured is not None and measured.audio_s > 0
                else None
            ),
        )

    async def _installed(self, track: _Track) -> set[str]:
        """The track's installed models, less the one still downloading.

        On Speaches, the models the server lists, less those an api killed mid-download left
        half-written (the server may list their folders). Raises `ProviderError`. On the GPU,
        the catalog's files that are complete in the models folder, and none without it.
        """
        kind, engine = track
        if engine == "whispercpp":
            ids = [entry.model_id for entry in self._catalog(track)]
            installed = await self._files.present(ids) if self._files is not None else set()
        else:
            installed = await self._servers[kind].installed()
            if self._files is not None:
                installed -= await self._files.incomplete()
        running = self._running()
        if running is not None:
            installed.discard(running.entry.model_id)
        return installed

    async def _is_installed(self, entry: CatalogEntry) -> bool:
        try:
            return entry.model_id in await self._installed(_track_of(entry))
        except ProviderError:
            return False

    async def _files_for(self, track: _Track) -> ModelFiles | None:
        """The model files when the track is manageable: with `VT_SPEECH_MODELS_DIR`, on Speaches
        and on the GPU engine (whose server need not be running)."""
        kind, engine = track
        if engine == "whispercpp":
            return self._files if self._gpu() is not None else None
        if self._files is not None and await self._servers[kind].is_speaches():
            return self._files
        return None

    def _entry(self, key: str) -> CatalogEntry:
        """The catalog entry for `key`, the configured defaults included. Raises 404."""
        found = next((e for track in _TRACKS for e in self._catalog(track) if e.key == key), None)
        if found is None:
            raise SpeechSettingsError(404, f"There is no speech model {key!r}.")
        return found

    def _catalog(self, track: _Track) -> list[CatalogEntry]:
        kind, engine = track
        return catalog(kind, self._default(track), engine)

    def _default(self, track: _Track) -> str:
        return _model(self._defaults, track)


def _track_of(entry: CatalogEntry) -> _Track:
    return entry.kind, entry.engine


def _model(settings: SpeechSettings, track: _Track) -> str:
    if track == _GPU:
        return settings.stt_gpu_model
    return settings.tts_model if track == _VOICE else settings.stt_model


def _unmanageable(track: _Track) -> SpeechSettingsError:
    where = "only with" if track == _GPU else "only on Speaches, with"
    return SpeechSettingsError(
        409,
        f"Models for {_WORDING[track].models_of} can be downloaded and uninstalled {where} "
        "VT_SPEECH_MODELS_DIR set (see docs/configuration.md).",
    )


def _voice_choice(model: str, voice: str, speed: float) -> VoiceChoice:
    """Piper models ask Speaches for the player's sample rate (the catalog knows which)."""
    entry = entry_for(model)
    return VoiceChoice(model, voice, speed, entry.sample_rate_hz if entry else None)
