"""Runtime configuration for `pron`.

Prefix `VT_PRON_`, so it can share the `.env` file with `api` without clashing
(`api` reads `VT_PORT`, `pron` reads `VT_PRON_PORT`). Reference: docs/configuration.md.
"""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VT_PRON_",
        env_file=".env",
        env_file_encoding="utf-8",
        # `VT_X=` (empty) means "use the default", not an empty string or path.
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    # Loopback when run on the host; the Docker image sets 0.0.0.0 (published on 127.0.0.1 only).
    host: str = "127.0.0.1"
    port: int = Field(default=8001, ge=1, le=65_535)
    log_level: LogLevel = "INFO"
