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

    # Chat model. These apply until a provider is saved from the UI (`settings_path`).
    llm_provider: ProviderKind = "openai_compatible"
    llm_base_url: HttpUrl = HttpUrl("http://llm:8080/v1")
    llm_model: str = "gemma-3-4b-it-q4"
    llm_api_key: SecretStr = SecretStr("")
    llm_temperature: float = Field(default=0.6, ge=0.0, le=2.0)

    # Speech-to-text
    stt_backend: SttBackend = "openai"
    stt_base_url: HttpUrl = HttpUrl("http://stt:8000/v1")
    stt_model: str = "large-v3-turbo"

    # Text-to-speech
    tts_base_url: HttpUrl = HttpUrl("http://tts:8880/v1")
    tts_voice: str = "af_heart"
    tts_speed: float = Field(default=0.95, gt=0.0, le=4.0)

    # Pronunciation scoring
    pron_base_url: HttpUrl = HttpUrl("http://pron:8001")

    # Voice activity detection
    vad_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    vad_min_silence_ms: int = Field(default=600, gt=0)

    # Learner
    learner_l1: str = Field(default="es", pattern=r"^[a-z]{2,3}$")
    learner_level: CefrLevel = "B1"
    # Language of correction explanations: English or the native language above.
    learner_explanations: ExplanationLanguage = "native"

    # Storage and privacy
    notes_dir: Path = Path("/data/notes")
    db_path: Path = Path("/data/progress.db")
    # Settings saved from the UI, API keys included (file mode 0600).
    settings_path: Path = Path("/data/settings.json")
    # Learner profile saved from the UI (level, explanation language).
    learner_profile_path: Path = Path("/data/learner.json")
    keep_audio: bool = False
