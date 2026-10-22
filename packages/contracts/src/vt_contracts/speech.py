"""Speech readiness: `GET /v1/speech/status`."""

from pydantic import BaseModel, ConfigDict


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
    synthesis: ModelStatus
    """Text-to-speech: the tutor's voice."""
