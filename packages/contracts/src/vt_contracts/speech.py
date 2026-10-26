"""Speech: readiness (`GET /v1/speech/status`) and the settings (`/v1/speech/...`)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type SpeechKind = Literal["recognition", "voice"]
# Speech recognition engines: Speaches (CPU, or an NVIDIA GPU) and whisper.cpp (a Vulkan GPU).
type SttEngine = Literal["openai", "whispercpp"]
type ModelState = Literal["installed", "downloading", "available"]


class ModelStatus(BaseModel):
    """Whether one speech server answers and has its model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str
    model: str
    reachable: bool
    """The server answered."""
    model_ready: bool
    """`model` is downloaded and listed by the server."""
    detail: str | None = None
    """Why it is not ready, in words the learner can act on."""


class SpeechStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    recognition: ModelStatus
    """Speech-to-text: the learner's voice."""
    recognition_engine: SttEngine
    """The engine `recognition` is on: the chosen one, or Speaches when whisper.cpp (GPU)
    cannot transcribe now."""
    synthesis: ModelStatus
    """Text-to-speech: the tutor's voice."""


class SpeechSettings(BaseModel):
    """Body of `PUT /v1/speech/settings`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stt_model: str
    """The Speaches model: a Hugging Face id, e.g. `Systran/faster-distil-whisper-small.en`."""
    stt_engine: SttEngine
    """The engine that transcribes the learner."""
    stt_gpu_model: str
    """The whisper.cpp model: a file of a Hugging Face repository, e.g.
    `ggerganov/whisper.cpp/ggml-small.en-q8_0.bin`. Each engine keeps its own choice."""
    tts_model: str
    tts_voice: str
    tts_speed: float = Field(ge=0.7, le=1.3)
    max_turn_s: int = Field(ge=30, le=300)
    """Longest learner turn kept, in seconds."""


class SpeechSettingsView(SpeechSettings):
    source: Literal["environment", "saved"]
    missing: list[SpeechKind] = []
    """Kinds whose saved model is not installed: the default is used instead."""
    pending: list[str] = []
    """Model ids that become active when their download ends."""


class DownloadProgress(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    done_bytes: int
    total_bytes: int | None


class SpeechModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    """Catalog slug, used in URLs."""
    kind: SpeechKind
    engine: SttEngine
    """The engine that runs it; voice models are all `openai` (Speaches)."""
    model_id: str
    label: str
    hint: str
    approx_mb: int
    english_only: bool
    state: ModelState
    download: DownloadProgress | None
    default: bool
    selected: bool
    from_configuration: bool
    """The environment default is not in the curated list."""
    ms_per_audio_s: float | None
    """Measured transcription speed (recognition only)."""


class SpeechEngineState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    engine: SttEngine
    running: bool
    """Its server answers: the engine can be chosen."""
    manageable: bool
    """Its models can be downloaded and uninstalled from here."""


class SpeechModels(BaseModel):
    """`GET /v1/speech/models`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    models: list[SpeechModel]
    recognition_manageable: bool
    """Speaches' speech recognition models can be downloaded and uninstalled from here."""
    voice_manageable: bool
    engines: list[SpeechEngineState]
    """The speech recognition engines: `openai`, then `whispercpp`."""
    last_error: str | None
    """The last failed download, until the next one starts."""


class Voice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    accent: Literal["american", "british"] | None
    gender: Literal["female", "male"] | None


class DownloadRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    activate: bool = False
    """Make the model the active choice when the download ends."""


class VoicePreview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    voice: str
    speed: float = Field(ge=0.7, le=1.3)
