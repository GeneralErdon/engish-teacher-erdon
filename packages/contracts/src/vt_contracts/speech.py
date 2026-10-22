"""Speech-to-text readiness: `GET /v1/speech/status`."""

from pydantic import BaseModel, ConfigDict


class SpeechStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str
    model: str
    reachable: bool
    """The speech-to-text server answered."""
    model_ready: bool
    """`model` is downloaded and listed by the server."""
    detail: str | None = None
    """Why it is not ready, in words the learner can act on."""
