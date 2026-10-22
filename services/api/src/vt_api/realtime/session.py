"""One conversation over `/ws/session`: the learner's turns, the tutor's streamed replies and
the corrections, which run alongside each reply.

A new message interrupts the reply in progress (barge-in) but not the correction of the
previous message: that feedback is still useful. Everything stops when the session closes.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal, assert_never

from vt_api.domain.llm import PROVIDERS, ChatMessage, ProviderError
from vt_api.ports.llm import ChatModel
from vt_api.services.learner import LearnerService
from vt_api.services.llm import LlmService
from vt_api.teacher.conversation import correction_messages, reply_messages
from vt_api.teacher.corrections import CorrectionParseError, parse_correction
from vt_contracts.learner import LearnerProfile
from vt_contracts.ws import (
    AssistantTextDelta,
    AssistantTextDone,
    ClientEvent,
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

logger = logging.getLogger(__name__)

type Send = Callable[[ServerEvent], Awaitable[None]]

HISTORY_LIMIT = 20
"""Messages sent to the model with each reply: enough context, bounded cost."""


@dataclass(frozen=True, slots=True)
class _Started:
    model: ChatModel
    profile: LearnerProfile
    topic: str | None


class ConversationSession:
    def __init__(
        self,
        *,
        send: Send,
        llm: LlmService,
        learner: LearnerService,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._send = send
        self._llm = llm
        self._learner = learner
        self._clock = clock
        self._started: _Started | None = None
        self._history: list[ChatMessage] = []
        self._turns = 0
        self._reply: asyncio.Task[None] | None = None
        self._corrections: set[asyncio.Task[None]] = set()

    async def handle(self, event: ClientEvent) -> bool:
        """Apply one client event. `False` once the session is over."""
        match event:
            case SessionStart():
                await self._start(event.topic)
            case InputText():
                await self.learner_said(event.text, "text")
            case InputInterrupt():
                await self.interrupt()
            case SessionEnd():
                await self.close()
                return False
            case _:
                assert_never(event)
        return True

    async def _start(self, topic: str | None) -> None:
        model, provider = await self._llm.active_chat()
        profile = await self._learner.profile()
        self._started = _Started(model, profile, topic)
        await self._send(
            SessionReady(
                level=profile.level, provider=PROVIDERS[provider.kind].label, model=provider.model
            )
        )

    async def learner_said(self, text: str, source: Literal["text", "voice"]) -> None:
        """Start a turn: interrupt the tutor, then reply and correct in parallel."""
        if self._started is None:
            await self._send(
                ErrorEvent(code="not_started", message="Send session.start first.", retryable=False)
            )
            return
        await self.interrupt()
        self._turns += 1
        turn_id = f"t{self._turns}"
        started_at = self._clock()
        self._history.append(ChatMessage("user", text))
        await self._send(TranscriptFinal(turn_id=turn_id, text=text, source=source))

        self._reply = asyncio.create_task(self._run_reply(self._started, turn_id, started_at))
        correction = asyncio.create_task(
            self._run_correction(self._started, turn_id, text, started_at)
        )
        self._corrections.add(correction)
        correction.add_done_callback(self._corrections.discard)

    async def interrupt(self) -> None:
        """Stop the reply in progress, if any; its partial text stays in the history."""
        if self._reply is not None:
            await _cancel(self._reply)
            self._reply = None

    async def close(self) -> None:
        await self.interrupt()
        for task in list(self._corrections):
            await _cancel(task)

    def _elapsed_ms(self, since: float) -> int:
        return round((self._clock() - since) * 1000)

    async def _run_reply(self, started: _Started, turn_id: str, since: float) -> None:
        messages = reply_messages(self._history[-HISTORY_LIMIT:], started.profile, started.topic)
        parts: list[str] = []
        first_token_ms: int | None = None
        try:
            async for chunk in started.model.stream(messages):
                if first_token_ms is None:
                    first_token_ms = self._elapsed_ms(since)
                parts.append(chunk)
                await self._send(AssistantTextDelta(turn_id=turn_id, text=chunk))
        except ProviderError as error:
            await self._send(ErrorEvent(code="llm_failed", message=error.message, retryable=True))
            return
        except asyncio.CancelledError:
            self._remember_reply(parts)
            with suppress(Exception):  # the socket may already be gone
                await self._send(
                    AssistantTextDone(turn_id=turn_id, text="".join(parts), interrupted=True)
                )
            raise
        reply_ms = self._elapsed_ms(since)
        self._remember_reply(parts)
        await self._send(AssistantTextDone(turn_id=turn_id, text="".join(parts)))
        await self._send(
            TurnMetrics(turn_id=turn_id, first_token_ms=first_token_ms, reply_ms=reply_ms)
        )

    def _remember_reply(self, parts: list[str]) -> None:
        if reply := "".join(parts):
            self._history.append(ChatMessage("assistant", reply))

    async def _run_correction(
        self, started: _Started, turn_id: str, text: str, since: float
    ) -> None:
        messages = correction_messages(text, started.profile, self._learner.native_language)
        try:
            raw = "".join([chunk async for chunk in started.model.stream(messages)])
            corrected, items = parse_correction(raw, text)
        except (ProviderError, CorrectionParseError) as error:
            # The conversation goes on without feedback for this message.
            logger.warning("No correction for turn %s: %s", turn_id, error)
            return
        await self._send(
            Correction(
                turn_id=turn_id,
                corrected=corrected,
                items=items,
                latency_ms=self._elapsed_ms(since),
            )
        )


async def _cancel(task: asyncio.Task[None]) -> None:
    task.cancel()
    # `wait` does not re-raise the task's CancelledError into the caller.
    await asyncio.wait([task])
