"""The realtime protocol on `/ws/session` (docs/architecture.md, "Realtime protocol").

Text frames carry these JSON events; binary frames will carry audio. Every event has a `type`
(the discriminator) and a protocol version `v`. The UI's TypeScript types are generated from
these models (they are added to the OpenAPI document, which does not describe WebSockets).
"""

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from vt_contracts.learner import CefrLevel

PROTOCOL_VERSION: Final = 1

type CorrectionKind = Literal["grammar", "vocabulary", "spelling", "naturalness"]
type ErrorCode = Literal["bad_event", "not_started", "llm_failed", "internal"]


class _Event(BaseModel):
    # In the generated TypeScript types, `type` and `v` must be required (they discriminate).
    model_config = ConfigDict(
        frozen=True, extra="forbid", json_schema_serialization_defaults_required=True
    )

    v: Literal[1] = PROTOCOL_VERSION


# ---------------------------------------------------------------- client -> server


class SessionStart(_Event):
    """Begin a conversation. Level and explanation language come from the learner profile."""

    type: Literal["session.start"] = "session.start"
    topic: str | None = Field(default=None, max_length=200)


class InputText(_Event):
    """A typed message from the learner."""

    type: Literal["input.text"] = "input.text"
    text: str = Field(min_length=1, max_length=4000)


class InputInterrupt(_Event):
    """Stop the tutor's current reply (the learner started a new turn or pressed stop)."""

    type: Literal["input.interrupt"] = "input.interrupt"


class SessionEnd(_Event):
    type: Literal["session.end"] = "session.end"


type ClientEvent = Annotated[
    SessionStart | InputText | InputInterrupt | SessionEnd, Field(discriminator="type")
]
CLIENT_EVENT: TypeAdapter[ClientEvent] = TypeAdapter(ClientEvent)


# ---------------------------------------------------------------- server -> client


class SessionReady(_Event):
    type: Literal["session.ready"] = "session.ready"
    level: CefrLevel
    provider: str
    """Label of the active chat model provider, e.g. "Ollama Cloud"."""
    model: str


class TranscriptFinal(_Event):
    """What the learner said (or typed) in this turn, as the server will use it."""

    type: Literal["transcript.final"] = "transcript.final"
    turn_id: str
    text: str
    source: Literal["text", "voice"]


class AssistantTextDelta(_Event):
    type: Literal["assistant.text.delta"] = "assistant.text.delta"
    turn_id: str
    text: str


class AssistantTextDone(_Event):
    type: Literal["assistant.text.done"] = "assistant.text.done"
    turn_id: str
    text: str
    """The whole reply (what was sent so far, if interrupted)."""
    interrupted: bool = False


class CorrectionItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    original: str
    suggestion: str
    kind: CorrectionKind
    explanation: str


class Correction(_Event):
    """Feedback on the learner's message. `corrected == text` and no items: nothing to fix."""

    type: Literal["correction"] = "correction"
    turn_id: str
    corrected: str
    items: list[CorrectionItem]
    latency_ms: int
    """From the learner's message to this event."""


class TurnMetrics(_Event):
    """Latency of the tutor's reply, in milliseconds, from the learner's message (Phase 0)."""

    type: Literal["turn.metrics"] = "turn.metrics"
    turn_id: str
    first_token_ms: int | None
    """Until the tutor's first word; `None` if the reply was empty."""
    reply_ms: int
    """Until the whole reply."""


class ErrorEvent(_Event):
    type: Literal["error"] = "error"
    code: ErrorCode
    message: str
    retryable: bool


type ServerEvent = Annotated[
    SessionReady
    | TranscriptFinal
    | AssistantTextDelta
    | AssistantTextDone
    | Correction
    | TurnMetrics
    | ErrorEvent,
    Field(discriminator="type"),
]
SERVER_EVENT: TypeAdapter[ServerEvent] = TypeAdapter(ServerEvent)
