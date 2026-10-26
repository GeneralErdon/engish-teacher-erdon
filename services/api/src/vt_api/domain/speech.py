"""Speech models: the curated catalog and the rules for choosing them.

Pure: no I/O. The Speaches adapter downloads and lists models, and `vt_api.services.speech`
ties them to the saved settings.
"""

from dataclasses import dataclass

from vt_api.domain.llm import ProviderError
from vt_contracts.speech import SpeechKind, SttEngine

# Piper makes 22.05 kHz audio. Speaches resamples when asked, so every voice streams at the
# rate the UI player expects.
PIPER_SAMPLE_RATE_HZ = 24_000
_GGML_REPO = "ggerganov/whisper.cpp"
DEFAULT_GPU_MODEL = f"{_GGML_REPO}/ggml-small.en-q8_0.bin"
"""The whisper.cpp model until another is chosen (`VT_STT_GPU_MODEL`): `just voice gpu`
downloads it before the server starts."""


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    key: str
    kind: SpeechKind
    model_id: str
    label: str
    hint: str
    approx_mb: int
    english_only: bool
    sample_rate_hz: int | None = None
    """The output rate to request. Set only for Piper."""
    engine: SttEngine = "openai"
    """The engine that runs it: whisper.cpp models are single GGML files."""


@dataclass(frozen=True, slots=True)
class VoiceChoice:
    """How the tutor speaks."""

    model: str
    voice: str
    speed: float
    sample_rate_hz: int | None = None


@dataclass(frozen=True, slots=True)
class Recognition:
    """The engine and model that transcribe the learner."""

    engine: SttEngine
    model: str
    """The catalog id, which measured speed and warnings name."""
    server_model: str
    """What the server is asked for: the model id on Speaches; on whisper.cpp, the file's path
    relative to the models folder (`ModelFiles.snapshot_path`)."""


@dataclass(frozen=True, slots=True)
class SessionSpeech:
    """What one conversation uses, fixed when it starts."""

    recognition: Recognition
    voice: VoiceChoice
    max_turn_s: int
    missing: tuple[SpeechKind, ...] = ()
    """Kinds whose saved model was not installed: the default stands in."""
    fallback: Recognition | None = None
    """Speaches, while the GPU transcribes: it takes over if the GPU server stops answering."""
    engine_unavailable: SttEngine | None = None
    """The chosen engine, when it cannot transcribe this conversation: Speaches stands in."""


def _recognition(
    key: str, model_id: str, label: str, hint: str, approx_mb: int, *, english_only: bool = True
) -> CatalogEntry:
    return CatalogEntry(key, "recognition", model_id, label, hint, approx_mb, english_only)


def _piper(key: str, model_id: str, label: str, hint: str) -> CatalogEntry:
    return CatalogEntry(key, "voice", model_id, label, hint, 63, True, PIPER_SAMPLE_RATE_HZ)


def _ggml(
    key: str, file: str, label: str, hint: str, approx_mb: int, *, english_only: bool = True
) -> CatalogEntry:
    return CatalogEntry(
        key,
        "recognition",
        f"{_GGML_REPO}/{file}",
        label,
        hint,
        approx_mb,
        english_only,
        engine="whispercpp",
    )


CATALOG: tuple[CatalogEntry, ...] = (
    _recognition(
        "whisper-tiny-en",
        "Systran/faster-whisper-tiny.en",
        "Whisper tiny (English)",
        "Fastest, least accurate",
        78,
    ),
    _recognition(
        "whisper-base-en",
        "Systran/faster-whisper-base.en",
        "Whisper base (English)",
        "Very fast",
        148,
    ),
    _recognition(
        "distil-whisper-small-en",
        "Systran/faster-distil-whisper-small.en",
        "Distil-Whisper small (English)",
        "Fast, good for most accents",
        336,
    ),
    _recognition(
        "whisper-small-en",
        "Systran/faster-whisper-small.en",
        "Whisper small (English)",
        "A bit slower, a bit more accurate",
        486,
    ),
    _recognition(
        "distil-whisper-medium-en",
        "Systran/faster-distil-whisper-medium.en",
        "Distil-Whisper medium (English)",
        "More accurate; slower on CPU",
        792,
    ),
    _recognition(
        "whisper-medium-en",
        "Systran/faster-whisper-medium.en",
        "Whisper medium (English)",
        "Accurate; slow on CPU",
        1530,
    ),
    _recognition(
        "distil-whisper-large-v3",
        "Systran/faster-distil-whisper-large-v3",
        "Distil-Whisper large v3",
        "Very accurate; GPU recommended",
        1516,
        english_only=False,
    ),
    _recognition(
        "whisper-large-v3-turbo",
        "deepdml/faster-whisper-large-v3-turbo-ct2",
        "Whisper large v3 turbo",
        "Most accurate; GPU recommended (multilingual)",
        1622,
        english_only=False,
    ),
    CatalogEntry(
        "kokoro",
        "voice",
        "speaches-ai/Kokoro-82M-v1.0-ONNX",
        "Kokoro",
        "Natural; 28 English voices (American and British, female and male)",
        354,
        True,
    ),
    CatalogEntry(
        "kokoro-int8",
        "voice",
        "speaches-ai/Kokoro-82M-v1.0-ONNX-int8",
        "Kokoro (compact)",
        "Same voices, smaller and faster on CPU, slightly lower quality",
        121,
        True,
    ),
    _piper(
        "piper-lessac",
        "speaches-ai/piper-en_US-lessac-medium",
        "Piper Lessac (American)",
        "Very light and fast, more robotic; one voice",
    ),
    _piper(
        "piper-ryan",
        "speaches-ai/piper-en_US-ryan-medium",
        "Piper Ryan (American, male)",
        "Very light and fast, more robotic; one male voice",
    ),
    _piper(
        "piper-alba",
        "speaches-ai/piper-en_GB-alba-medium",
        "Piper Alba (British)",
        "Very light and fast, more robotic; one British female voice",
    ),
    _piper(
        "piper-alan",
        "speaches-ai/piper-en_GB-alan-medium",
        "Piper Alan (British, male)",
        "Very light and fast, more robotic; one British male voice",
    ),
    _ggml(
        "whispercpp-base-en",
        "ggml-base.en.bin",
        "Whisper base (English)",
        "Fastest, least accurate",
        148,
    ),
    _ggml(
        "whispercpp-small-en-q8",
        "ggml-small.en-q8_0.bin",
        "Whisper small (English, 8-bit)",
        "Fast and accurate on a GPU",
        264,
    ),
    _ggml(
        "whispercpp-medium-en-q5",
        "ggml-medium.en-q5_0.bin",
        "Whisper medium (English, 5-bit)",
        "More accurate",
        539,
    ),
    _ggml(
        "whispercpp-large-v3-turbo-q5",
        "ggml-large-v3-turbo-q5_0.bin",
        "Whisper large v3 turbo (5-bit)",
        "The accurate choice (multilingual)",
        574,
        english_only=False,
    ),
    _ggml(
        "whispercpp-large-v3-turbo-q8",
        "ggml-large-v3-turbo-q8_0.bin",
        "Whisper large v3 turbo (8-bit)",
        "Most accurate; more GPU memory (multilingual)",
        874,
        english_only=False,
    ),
    _ggml(
        "whispercpp-large-v3-turbo",
        "ggml-large-v3-turbo.bin",
        "Whisper large v3 turbo (full)",
        "Full precision; the most GPU memory (multilingual)",
        1625,
        english_only=False,
    ),
)


def catalog(
    kind: SpeechKind, default_model_id: str, engine: SttEngine = "openai"
) -> list[CatalogEntry]:
    """The curated models of one kind on one engine, plus the configured default when it is
    not among them."""
    entries = [e for e in CATALOG if e.kind == kind and e.engine == engine]
    if any(e.model_id == default_model_id for e in entries):
        return entries
    slug = default_model_id.rsplit("/", 1)[-1].lower().replace(".", "-").replace("_", "-")
    entries.append(
        CatalogEntry(
            key=f"configured-{slug}",
            kind=kind,
            model_id=default_model_id,
            label=default_model_id.rsplit("/", 1)[-1],
            hint="Set in the configuration",
            approx_mb=0,
            english_only=False,
            engine=engine,
        )
    )
    return entries


def single_file_repos(gpu_default: str) -> frozenset[str]:
    """The repositories whose models are single files, not whole repositories: those of the
    whisper.cpp catalog and of the configured GPU default (`org/name/file`)."""
    model_ids = [e.model_id for e in CATALOG if e.engine == "whispercpp"] + [gpu_default]
    return frozenset(split_model_id(model_id)[0] for model_id in model_ids)


def entry(key: str) -> CatalogEntry | None:
    return next((e for e in CATALOG if e.key == key), None)


def entry_for(model_id: str) -> CatalogEntry | None:
    return next((e for e in CATALOG if e.model_id == model_id), None)


def split_model_id(model_id: str) -> tuple[str, str | None]:
    """`org/name` is a whole repository; `org/name/file.bin` is one file of one.

    Raises `ValueError` for more than three segments or an empty one.
    """
    parts = model_id.split("/")
    if len(parts) not in (2, 3) or any(part == "" for part in parts):
        raise ValueError(f"Not a repo id (org/name) or a file of one (org/name/file): {model_id!r}")
    return "/".join(parts[:2]), (parts[2] if len(parts) == 3 else None)


def transcription_timeout_s(audio_s: float) -> float:
    """Time allowed to transcribe a turn: a fixed allowance plus 3x the audio (slow CPUs)."""
    return 30 + 3 * audio_s


class SpeechSettingsError(Exception):
    """A speech settings request the api refuses, in words the learner can act on.

    `status` is the HTTP status the route answers with: 404 (unknown model), 409 (busy),
    422 (invalid choice), 500 (model files that cannot be removed), 502 (the speech server or
    Hugging Face failed) or 507 (no disk space).
    """

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class EngineUnreachable(ProviderError):  # noqa: N818 (a condition, named for what happened)
    """The GPU speech server refused the connection: it is not running (or has just exited).

    Unlike a timeout or an error answer, it tells a conversation to fall back to the CPU engine.
    """

    def __init__(self, base_url: str) -> None:
        super().__init__("connection", f"Could not connect to {base_url}.")
