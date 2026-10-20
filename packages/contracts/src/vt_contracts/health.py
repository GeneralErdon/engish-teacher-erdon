"""Liveness response shared by every voice-tutor service."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Body of `GET /healthz`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ok"]
    service: Literal["api", "pron"]
    version: str
