"""The speech choices saved from the UI (defaults from `VT_STT_MODEL`, `VT_TTS_*` and
`VT_MAX_TURN_S`), model downloads, and the choice each conversation uses.

Models are downloaded and uninstalled only where a kind is *manageable*: Speaches, with
`VT_SPEECH_MODELS_DIR` set. Any other OpenAI-compatible server keeps working, with read-only lists.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from vt_api.domain.audio import to_wav
from vt_api.domain.llm import ProviderError
from vt_api.domain.speech import (
    CatalogEntry,
    SessionSpeech,
    SpeechSettingsError,
    VoiceChoice,
    catalog,
    entry_for,
    transcription_timeout_s,
)
from vt_api.ports.speech import (
    ModelFiles,
    SpeechModelServer,
    SpeechSettingsRepository,
    SpeechToText,
    TextToSpeech,
)
from vt_contracts.audio import OUTPUT_SAMPLE_RATE_HZ
from vt_contracts.speech import (
    SpeechKind,
    SpeechModel,
    SpeechModels,
    SpeechSettings,
    SpeechSettingsView,
    SpeechStatus,
    Voice,
    VoicePreview,
)

logger = logging.getLogger(__name__)

PREVIEW_TEXT = "Hi! I'm your English tutor. Shall we practise together?"
_NOT_SEEN_BY_SPEACHES = (
    "Downloaded, but Speaches does not see it: VT_SPEECH_MODELS_DIR must be the folder Speaches "
    "reads (see docs/configuration.md)"
)
_KINDS: tuple[SpeechKind, ...] = ("recognition", "voice")
_NAMES: dict[SpeechKind, str] = {"recognition": "speech recognition", "voice": "voice"}


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
        missing = (await self._session(settings)).missing
        return self._view(settings, saved=saved is not None, missing=missing)

    async def save(self, settings: SpeechSettings) -> SpeechSettingsView:
        """Checks only what changed, so a saved model that went missing, or a server that does
        not answer, never blocks the speed or the turn length.

        Raises `SpeechSettingsError`: 422 for a model that is not installed or a voice the model
        does not have, 502 when the server cannot tell what is installed."""
        async with self._settings_lock:
            current = await self._settings()
            for kind in _KINDS:
                if _model(settings, kind) != _model(current, kind):
                    await self._check_installed(kind, _model(settings, kind))
            if (settings.tts_model, settings.tts_voice) != (current.tts_model, current.tts_voice):
                voices = {voice.id for voice in await self.voices(settings.tts_model)}
                if voices and settings.tts_voice not in voices:
                    raise SpeechSettingsError(
                        422, f"{settings.tts_model} has no voice {settings.tts_voice!r}."
                    )
            await self._store(settings, current)
        missing = (await self._session(settings)).missing
        return self._view(settings, saved=True, missing=missing)

    async def models(self) -> SpeechModels:
        settings = await self._settings()
        (recognition, recognition_manageable), (voice, voice_manageable) = await asyncio.gather(
            self._kind_models("recognition", settings.stt_model),
            self._kind_models("voice", settings.tts_model),
        )
        return SpeechModels(
            models=recognition + voice,
            recognition_manageable=recognition_manageable,
            voice_manageable=voice_manageable,
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
        files = await self._files_for(entry.kind)
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
            raise _unmanageable(entry.kind)
        else:
            download = _Download(entry, activate)
            download.task = asyncio.create_task(self._run(download, files))
            self._download = download
            self._last_error = None
        return await self.models()

    async def cancel_download(self) -> None:
        """Stop the download in progress, if any; its activation goes with it."""
        await self._stop()

    async def uninstall(self, key: str) -> None:
        """Raises `SpeechSettingsError`: 404 for an unknown key; 409 for the default, the selected
        or the downloading model, or one that cannot be managed here; 500 when its files cannot be
        removed."""
        entry = self._entry(key)
        if entry.model_id == self._default(entry.kind):
            raise SpeechSettingsError(409, f"{entry.label} is the default and stays installed.")
        if entry.model_id == _model(await self._settings(), entry.kind):
            raise SpeechSettingsError(409, f"{entry.label} is in use: choose another model first.")
        running = self._running()
        if running is not None and running.entry == entry:
            raise SpeechSettingsError(
                409, f"{entry.label} is downloading: cancel the download first."
            )
        files = await self._files_for(entry.kind)
        if files is None:
            raise _unmanageable(entry.kind)
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
        """The choice for a conversation that starts now."""
        return await self._session(await self._settings())

    async def transcribe(self, wav: bytes, audio_s: float, model: str) -> str:
        """Raises `ProviderError`. Records how long `model` took, for the turn-length estimate."""
        started = self._clock()
        text = await self._stt.transcribe(wav, model, transcription_timeout_s(audio_s))
        measured = self._measured.setdefault(model, _Measured())
        measured.audio_s += audio_s
        measured.ms += (self._clock() - started) * 1000
        return text

    def synthesize(self, text: str, voice: VoiceChoice) -> AsyncIterator[bytes]:
        return self._tts.synthesize(text, voice)

    async def status(self) -> SpeechStatus:
        """Whether the selected models are ready on their servers."""
        settings = await self._settings()
        recognition, synthesis = await asyncio.gather(
            self._stt.status(settings.stt_model), self._tts.status(settings.tts_model)
        )
        return SpeechStatus(recognition=recognition, synthesis=synthesis)

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

    async def _session(self, settings: SpeechSettings) -> SessionSpeech:
        """A saved model that is no longer installed gives way to its kind's default."""
        used = await asyncio.gather(
            *(self._installed_or_default(kind, _model(settings, kind)) for kind in _KINDS)
        )
        stt_model, tts_model = used
        voice = settings.tts_voice if tts_model == settings.tts_model else self._defaults.tts_voice
        return SessionSpeech(
            stt_model=stt_model,
            voice=_voice_choice(tts_model, voice, settings.tts_speed),
            max_turn_s=settings.max_turn_s,
            missing=tuple(
                kind
                for kind, model in zip(_KINDS, used, strict=True)
                if model != _model(settings, kind)
            ),
        )

    async def _installed_or_default(self, kind: SpeechKind, model_id: str) -> str:
        """`model_id`, unless the server says it is not installed (when it does not answer, a
        voice turn reports that itself)."""
        if model_id == self._default(kind):
            return model_id
        try:
            installed = await self._installed(kind)
        except ProviderError:
            return model_id
        return model_id if model_id in installed else self._default(kind)

    async def _check_installed(self, kind: SpeechKind, model_id: str) -> None:
        if model_id == self._default(kind):  # always installed: Speaches preloads it
            return
        if all(entry.model_id != model_id for entry in self._catalog(kind)):
            raise SpeechSettingsError(422, f"{model_id} is not a {_NAMES[kind]} model.")
        try:
            installed = await self._installed(kind)
        except ProviderError as error:
            raise SpeechSettingsError(
                502, f"Could not check that {model_id} is installed: {error.message}"
            ) from error
        if model_id not in installed:
            raise SpeechSettingsError(422, f"{model_id} is not installed: download it first.")

    async def _store(self, chosen: SpeechSettings, current: SpeechSettings) -> None:
        """Save `chosen`, under `_settings_lock`. Changing a kind's model drops the activation of
        that kind's download: the latest choice wins."""
        running = self._running()
        if running is not None:
            kind = running.entry.kind
            if _model(chosen, kind) != _model(current, kind):
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
            if entry.kind == "recognition":
                chosen = current.model_copy(update={"stt_model": entry.model_id})
            else:
                keep = not voices or current.tts_voice in voices
                voice = current.tts_voice if keep else voices[0]
                chosen = current.model_copy(
                    update={"tts_model": entry.model_id, "tts_voice": voice}
                )
            await self._store(chosen, current)

    async def _run(self, download: _Download, files: ModelFiles) -> None:
        """The background download. A failure ends up in `last_error`, never as an unretrieved
        task exception; a cancel ends it quietly."""
        entry = download.entry
        try:
            await files.download(entry.model_id)
            # The server itself, not `_installed()`: that leaves out the model still downloading.
            if entry.model_id not in await self._servers[entry.kind].installed():
                self._last_error = _NOT_SEEN_BY_SPEACHES
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

    async def _kind_models(self, kind: SpeechKind, selected: str) -> tuple[list[SpeechModel], bool]:
        """The kind's catalog with each model's state, and whether its models can be managed.
        A server that does not answer has nothing installed and cannot be managed."""
        try:
            installed = await self._installed(kind)
        except ProviderError:
            installed, manageable = set(), False
        else:
            manageable = await self._files_for(kind) is not None
        rows = [self._model_row(entry, installed, selected) for entry in self._catalog(kind)]
        return rows, manageable

    def _model_row(self, entry: CatalogEntry, installed: set[str], selected: str) -> SpeechModel:
        """`download` stays `None` until the files report bytes, and once they are complete."""
        running = self._running()
        downloading = running is not None and running.entry == entry
        progress = self._files.progress() if downloading and self._files is not None else None
        measured = self._measured.get(entry.model_id)
        return SpeechModel(
            key=entry.key,
            kind=entry.kind,
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
            default=entry.model_id == self._default(entry.kind),
            selected=entry.model_id == selected,
            from_configuration=entry_for(entry.model_id) is None,
            ms_per_audio_s=(
                round(measured.ms / measured.audio_s, 1)
                if measured is not None and measured.audio_s > 0
                else None
            ),
        )

    async def _installed(self, kind: SpeechKind) -> set[str]:
        """The server's installed models, less those whose files are half-written: one still
        downloading, or one an api killed mid-download left (the server may list their folders).
        Raises `ProviderError`."""
        installed = await self._servers[kind].installed()
        if self._files is not None:
            installed -= await self._files.incomplete()
        running = self._running()
        if running is not None:
            installed.discard(running.entry.model_id)
        return installed

    async def _is_installed(self, entry: CatalogEntry) -> bool:
        try:
            return entry.model_id in await self._installed(entry.kind)
        except ProviderError:
            return False

    async def _files_for(self, kind: SpeechKind) -> ModelFiles | None:
        """The model files when the kind is manageable: Speaches, with `VT_SPEECH_MODELS_DIR`."""
        if self._files is not None and await self._servers[kind].is_speaches():
            return self._files
        return None

    def _entry(self, key: str) -> CatalogEntry:
        """The catalog entry for `key`, the configured defaults included. Raises 404."""
        found = next((e for kind in _KINDS for e in self._catalog(kind) if e.key == key), None)
        if found is None:
            raise SpeechSettingsError(404, f"There is no speech model {key!r}.")
        return found

    def _catalog(self, kind: SpeechKind) -> list[CatalogEntry]:
        return catalog(kind, self._default(kind))

    def _default(self, kind: SpeechKind) -> str:
        return _model(self._defaults, kind)


def _model(settings: SpeechSettings, kind: SpeechKind) -> str:
    return settings.stt_model if kind == "recognition" else settings.tts_model


def _unmanageable(kind: SpeechKind) -> SpeechSettingsError:
    return SpeechSettingsError(
        409,
        f"Models for {_NAMES[kind]} can be downloaded and uninstalled only on Speaches, with "
        "VT_SPEECH_MODELS_DIR set (see docs/configuration.md).",
    )


def _voice_choice(model: str, voice: str, speed: float) -> VoiceChoice:
    """Piper models ask Speaches for the player's sample rate (the catalog knows which)."""
    entry = entry_for(model)
    return VoiceChoice(model, voice, speed, entry.sample_rate_hz if entry else None)
