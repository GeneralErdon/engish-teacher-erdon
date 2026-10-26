"""Runtime configuration: the only module that reads the environment.

Every variable uses the `VT_` prefix and is validated at startup, so a bad value stops the
service with a clear error. Reference: docs/configuration.md.
"""

from pathlib import Path
from typing import Literal

from pydantic import DirectoryPath, Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from vt_contracts.learner import CefrLevel, ExplanationLanguage
from vt_contracts.llm import ProviderKind

type Profile = Literal["cpu", "nvidia", "amd", "external"]
type SttBackend = Literal["openai", "whispercpp"]
type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

DEFAULT_CORS_ORIGINS = (
    "tauri://localhost",  # desktop app on Linux and macOS
    "http://tauri.localhost",  # desktop app on Windows
    "http://localhost:1420",  # Vite dev server (`just dev`, `just desktop`)
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VT_",
        env_file=".env",
        env_file_encoding="utf-8",
        # `VT_X=` (empty) means "use the default", not an empty string or path.
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    # Server
    profile: Profile = "cpu"
    # Loopback when run on the host; the Docker image sets 0.0.0.0 (published on 127.0.0.1 only).
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65_535)
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    ui_dir: DirectoryPath | None = None
    log_level: LogLevel = "INFO"

    # Chat model. These apply until a provider is saved from the UI (in the database).
    llm_provider: ProviderKind = "openai_compatible"
    llm_base_url: HttpUrl = HttpUrl("http://llm:8080/v1")
    llm_model: str = "gemma-3-4b-it-q4"
    llm_api_key: SecretStr = SecretStr("")
    llm_temperature: float = Field(default=0.6, ge=0.0, le=2.0)

    # Speech-to-text
    stt_backend: SttBackend = "openai"
    stt_base_url: HttpUrl = HttpUrl("http://stt:8000/v1")
    # Speaches model id. CPU: distil small.en (fast). GPU: Systran/faster-whisper-large-v3-turbo.
    stt_model: str = "Systran/faster-distil-whisper-small.en"

    # Text-to-speech: Kokoro, served by the same Speaches as speech-to-text.
    tts_base_url: HttpUrl = HttpUrl("http://tts:8000/v1")
    tts_model: str = "speaches-ai/Kokoro-82M-v1.0-ONNX"
    tts_voice: str = "af_heart"
    # Slightly slower than normal helps learners. Same range as the Settings screen.
    tts_speed: float = Field(default=0.95, ge=0.7, le=1.3)
    # Longest learner turn kept, in seconds (the rest is cut).
    max_turn_s: int = Field(default=120, ge=30, le=300)
    # The Hugging Face cache folder shared with Speaches: the api downloads and removes speech
    # models there, and creates it if missing. Unset: the model lists are read-only.
    speech_models_dir: Path | None = None

    # Pronunciation scoring
    pron_base_url: HttpUrl = HttpUrl("http://pron:8001")

    # Learner
    learner_l1: str = Field(default="es", pattern=r"^[a-z]{2,3}$")
    learner_level: CefrLevel = "B1"
    # Language of correction explanations: English or the native language above.
    learner_explanations: ExplanationLanguage = "native"

    # Storage and privacy
    notes_dir: Path = Path("/data/notes")
    # Settings saved from the UI, API keys included: SQLite encrypted with SQLCipher (file mode
    # 0600). Only SQLite for now. Three slashes and a relative path, or four and an absolute one.
    database_url: str = Field(
        default="sqlite:////data/voice-tutor.db", pattern=r"^sqlite:///[^?]+$"
    )
    # Master key of the database (base64, 32 bytes). Unset: the key file below if it exists,
    # else the OS keyring (desktop), else a new key file. See docs/configuration.md#encryption.
    secret_key: SecretStr | None = None
    secret_key_file: Path = Path("/data/secret.key")
    # Keep the key in the OS keyring when there is one. Off: always the key file.
    keyring: bool = True
    keep_audio: bool = False
