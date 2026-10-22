"""The conversation session with a scripted chat model: no network, deterministic timing."""

import asyncio
import itertools
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

import pytest
from pydantic import SecretStr

from vt_api.domain.llm import ChatMessage, LlmConfig, ProviderConfig, ProviderError
from vt_api.ports.llm import ChatModel
from vt_api.realtime.session import ConversationSession
from vt_api.services.learner import LearnerService
from vt_api.services.llm import LlmService
from vt_contracts.ws import (
    AssistantTextDelta,
    AssistantTextDone,
    Correction,
    ErrorEvent,
    InputInterrupt,
    InputText,
    ServerEvent,
    SessionEnd,
    SessionReady,
    SessionStart,
    TranscriptFinal,
    TurnMetrics,
)

CORRECTION = json.dumps(
    {
        "corrected": "I went to the beach",
        "items": [
            {
                "original": "have went",
                "suggestion": "went",
                "kind": "grammar",
                "explanation": "Pasado simple.",
            }
        ],
    }
)


@dataclass
class ScriptedChat:
    """Replies with `reply`; answers correction prompts with `correction`."""

    reply: Sequence[str] = ("Nice", "! What did you do?")
    correction: str = CORRECTION
    reply_error: ProviderError | None = None
    correction_error: ProviderError | None = None
    hold: asyncio.Event | None = None
    """When set, the reply waits on it after its first chunk (to test interruptions)."""
    seen: list[list[ChatMessage]] = field(default_factory=list)

    async def stream(
        self, messages: Sequence[ChatMessage], *, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        self.seen.append(list(messages))
        if "corrections as JSON" in messages[0].content:
            if self.hold:
                await self.hold.wait()
            if self.correction_error:
                raise self.correction_error
            yield self.correction
            return
        if self.reply_error:
            raise self.reply_error
        for index, chunk in enumerate(self.reply):
            if index == 1 and self.hold:
                await self.hold.wait()
            yield chunk

    async def list_models(self) -> list[str]:
        return []


class Memory:
    def __init__(self) -> None:
        self.config: LlmConfig | None = None

    async def load(self) -> LlmConfig | None:
        return self.config

    async def save(self, config: LlmConfig) -> None:
        self.config = config

    async def clear(self) -> None:
        self.config = None


@pytest.fixture
def chat() -> ScriptedChat:
    return ScriptedChat()


@pytest.fixture
def events() -> list[ServerEvent]:
    return []


@pytest.fixture
def session(
    chat: ScriptedChat, events: list[ServerEvent], learner_service: LearnerService
) -> ConversationSession:
    def factory(provider: ProviderConfig) -> ChatModel:
        return chat

    environment = LlmConfig(
        active="ollama_cloud",
        providers={
            "ollama_cloud": ProviderConfig(
                "ollama_cloud", "https://ollama.com", "gpt-oss:120b", SecretStr("k")
            )
        },
        source="environment",
    )
    llm = LlmService(repository=Memory(), chat_models=factory, environment=environment)
    ticks = itertools.count()

    async def send(event: ServerEvent) -> None:
        events.append(event)

    # Each clock read advances 100 ms, so latencies are predictable.
    return ConversationSession(
        send=send, llm=llm, learner=learner_service, clock=lambda: next(ticks) / 10
    )


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


def _of[E](kind: type[E], events: list[ServerEvent]) -> list[E]:
    return [event for event in events if isinstance(event, kind)]


async def test_a_text_turn(session: ConversationSession, events: list[ServerEvent]) -> None:
    await session.handle(SessionStart())
    await session.handle(InputText(text="I have went to the beach"))
    await _settle()

    assert events[0] == SessionReady(level="B1", provider="Ollama Cloud", model="gpt-oss:120b")
    assert events[1] == TranscriptFinal(
        turn_id="t1", text="I have went to the beach", source="text"
    )
    assert [e.text for e in _of(AssistantTextDelta, events)] == ["Nice", "! What did you do?"]
    assert _of(AssistantTextDone, events) == [
        AssistantTextDone(turn_id="t1", text="Nice! What did you do?")
    ]
    [metrics] = _of(TurnMetrics, events)
    assert metrics.first_token_ms is not None
    assert metrics.reply_ms >= metrics.first_token_ms
    [correction] = _of(Correction, events)
    assert correction.corrected == "I went to the beach"
    assert correction.items[0].explanation == "Pasado simple."


async def test_the_tutor_remembers_the_conversation(
    session: ConversationSession, chat: ScriptedChat
) -> None:
    await session.handle(SessionStart(topic="holidays"))
    await session.handle(InputText(text="Hello"))
    await _settle()
    await session.handle(InputText(text="I like the sea"))
    await _settle()

    replies = [m for m in chat.seen if "corrections as JSON" not in m[0].content]
    assert "Today's topic: holidays." in replies[-1][0].content
    assert [m.content for m in replies[-1][1:]] == [
        "Hello",
        "Nice! What did you do?",
        "I like the sea",
    ]


async def test_a_new_message_interrupts_the_reply(
    session: ConversationSession, chat: ScriptedChat, events: list[ServerEvent]
) -> None:
    chat.hold = asyncio.Event()
    await session.handle(SessionStart())
    await session.handle(InputText(text="Hello"))
    await _settle()

    await session.handle(InputText(text="Wait, one more thing"))
    chat.hold.set()
    await _settle()

    done = _of(AssistantTextDone, events)
    assert done[0] == AssistantTextDone(turn_id="t1", text="Nice", interrupted=True)
    assert done[1].turn_id == "t2"
    # Both messages are still corrected.
    assert sorted(c.turn_id for c in _of(Correction, events)) == ["t1", "t2"]


async def test_explicit_interrupt(
    session: ConversationSession, chat: ScriptedChat, events: list[ServerEvent]
) -> None:
    chat.hold = asyncio.Event()
    await session.handle(SessionStart())
    await session.handle(InputText(text="Hello"))
    await _settle()

    assert await session.handle(InputInterrupt())
    assert _of(AssistantTextDone, events)[-1].interrupted is True
    assert await session.handle(InputInterrupt())  # nothing to stop: fine


async def test_messages_before_start_are_rejected(
    session: ConversationSession, events: list[ServerEvent]
) -> None:
    await session.handle(InputText(text="Hello"))

    assert events == [
        ErrorEvent(code="not_started", message="Send session.start first.", retryable=False)
    ]


async def test_provider_failures_are_reported(
    session: ConversationSession, chat: ScriptedChat, events: list[ServerEvent]
) -> None:
    chat.reply_error = ProviderError("auth", "The provider rejected the API key (HTTP 401).")
    chat.correction_error = ProviderError("auth", "nope")
    await session.handle(SessionStart())
    await session.handle(InputText(text="Hello"))
    await _settle()

    assert _of(ErrorEvent, events) == [
        ErrorEvent(
            code="llm_failed",
            message="The provider rejected the API key (HTTP 401).",
            retryable=True,
        )
    ]
    assert _of(Correction, events) == []


async def test_unusable_corrections_are_skipped(
    session: ConversationSession, chat: ScriptedChat, events: list[ServerEvent]
) -> None:
    chat.correction = "I think it is fine!"
    await session.handle(SessionStart())
    await session.handle(InputText(text="Hello"))
    await _settle()

    assert _of(Correction, events) == []
    assert len(_of(AssistantTextDone, events)) == 1


async def test_an_empty_reply_has_no_first_token(
    session: ConversationSession, chat: ScriptedChat, events: list[ServerEvent]
) -> None:
    chat.reply = ()
    await session.handle(SessionStart())
    await session.handle(InputText(text="Hello"))
    await _settle()

    assert _of(TurnMetrics, events)[0].first_token_ms is None


async def test_ending_stops_everything(
    session: ConversationSession, chat: ScriptedChat, events: list[ServerEvent]
) -> None:
    chat.hold = asyncio.Event()
    await session.handle(SessionStart())
    await session.handle(InputText(text="Hello"))

    assert await session.handle(SessionEnd()) is False
    chat.hold.set()
    await _settle()

    assert _of(TurnMetrics, events) == []
    assert _of(Correction, events) == []
