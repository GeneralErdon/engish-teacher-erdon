"""One conversation over `/ws/session`: the learner's turns (typed, or spoken and transcribed),
the tutor's streamed replies, spoken sentence by sentence when the learner wants a voice, and
the corrections, which run alongside each reply.

A new message interrupts the reply in progress (barge-in), its voice included, but not the
correction of the previous message: that feedback is still useful. Everything stops when the
session closes.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal, assert_never

from vt_api.domain.audio import duration_s, to_wav
from vt_api.domain.llm import PROVIDERS, ChatMessage, ProviderError
from vt_api.ports.llm import ChatModel
from vt_api.ports.speech import SpeechToText, TextToSpeech
from vt_api.realtime.sentences import SentenceSplitter, speakable
from vt_api.services.learner import LearnerService
from vt_api.services.llm import LlmService
from vt_api.teacher.conversation import correction_messages, reply_messages
from vt_api.teacher.corrections import CorrectionParseError, parse_correction
from vt_contracts.audio import OUTPUT_SAMPLE_RATE_HZ
from vt_contracts.learner import LearnerProfile
from vt_contracts.ws import (
    AssistantAudioDone,
    AssistantAudioStarted,
    AssistantTextDelta,
    AssistantTextDone,
    ClientEvent,
    Correction,
    ErrorCode,
    ErrorEvent,
    InputCommit,
    InputInterrupt,
    InputText,
    ServerEvent,
    SessionEnd,
    SessionReady,
    SessionStart,
    SessionUpdate,
    TranscriptFinal,
    TurnMetrics,
)

logger = logging.getLogger(__name__)

type Send = Callable[[ServerEvent], Awaitable[None]]
type SendAudio = Callable[[bytes], Awaitable[None]]

HISTORY_LIMIT = 20
"""Messages sent to the model with each reply: enough context, bounded cost."""

MIN_SPEECH_S = 0.3
"""Shorter recordings are accidental clicks, not speech."""
MAX_SPEECH_S = 60.0
"""Bounds the memory one connection can use; longer turns are not conversation."""


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
        send_audio: SendAudio,
        llm: LlmService,
        learner: LearnerService,
        stt: SpeechToText,
        tts: TextToSpeech,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._send = send
        self._send_audio = send_audio
        self._llm = llm
        self._learner = learner
        self._stt = stt
        self._tts = tts
        self._clock = clock
        self._started: _Started | None = None
        self._speak = False
        self._history: list[ChatMessage] = []
        self._turns = 0
        self._reply: asyncio.Task[None] | None = None
        self._background: set[asyncio.Task[None]] = set()
        """Corrections and transcriptions: they outlive interruptions, not the session."""
        self._audio = bytearray()
        self._audio_overflow = False

    async def handle(self, event: ClientEvent) -> bool:
        """Apply one client event. `False` once the session is over."""
        match event:
            case SessionStart():
                self._speak = event.speak
                await self._start(event.topic)
            case SessionUpdate():
                self._speak = event.speak
            case InputText():
                await self.learner_said(event.text, "text")
            case InputCommit():
                await self._commit_audio()
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

    def audio(self, chunk: bytes) -> None:
        """Buffer microphone audio until `input.commit`."""
        if duration_s(len(self._audio) + len(chunk)) > MAX_SPEECH_S:
            self._audio_overflow = True
            return
        self._audio.extend(chunk)

    async def _commit_audio(self) -> None:
        pcm, overflow = bytes(self._audio), self._audio_overflow
        self._audio.clear()
        self._audio_overflow = False
        if self._started is None:
            await self._not_started()
            return
        if overflow:
            await self._error("audio_too_long", f"Keep each turn under {MAX_SPEECH_S:.0f} s.")
        elif duration_s(len(pcm)) < MIN_SPEECH_S:
            await self._error(
                "audio_too_short", "Too short: press the mic, speak, then press it again."
            )
        else:
            self._track(asyncio.create_task(self._run_voice(pcm)))

    async def _run_voice(self, pcm: bytes) -> None:
        since = self._clock()
        try:
            text = await self._stt.transcribe(to_wav(pcm))
        except ProviderError as error:
            await self._error("stt_failed", f"Speech recognition failed. {error.message}")
            return
        if not text:
            await self._error("no_speech", "I did not catch that. Try again, closer to the mic.")
            return
        await self.learner_said(text, "voice", stt_ms=self._elapsed_ms(since))

    async def _not_started(self) -> None:
        await self._send(
            ErrorEvent(code="not_started", message="Send session.start first.", retryable=False)
        )

    async def _error(self, code: ErrorCode, message: str) -> None:
        await self._send(ErrorEvent(code=code, message=message, retryable=True))

    def _track(self, task: asyncio.Task[None]) -> None:
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def learner_said(
        self, text: str, source: Literal["text", "voice"], stt_ms: int | None = None
    ) -> None:
        """Start a turn: interrupt the tutor, then reply and correct in parallel."""
        if self._started is None:
            await self._not_started()
            return
        await self.interrupt()
        self._turns += 1
        turn_id = f"t{self._turns}"
        started_at = self._clock()
        self._history.append(ChatMessage("user", text))
        await self._send(TranscriptFinal(turn_id=turn_id, text=text, source=source, stt_ms=stt_ms))

        self._reply = asyncio.create_task(self._run_reply(self._started, turn_id, started_at))
        self._track(
            asyncio.create_task(self._run_correction(self._started, turn_id, text, started_at))
        )

    async def interrupt(self) -> None:
        """Stop the reply in progress and its voice, if any; its partial text stays in the
        history."""
        if self._reply is not None:
            await _cancel(self._reply)
            self._reply = None

    async def close(self) -> None:
        await self.interrupt()
        for task in list(self._background):
            await _cancel(task)

    def _elapsed_ms(self, since: float) -> int:
        return round((self._clock() - since) * 1000)

    async def _run_reply(self, started: _Started, turn_id: str, since: float) -> None:
        messages = reply_messages(self._history[-HISTORY_LIMIT:], started.profile, started.topic)
        speaker = (
            _Speaker(
                self._tts, self._send, self._send_audio, turn_id, lambda: self._elapsed_ms(since)
            )
            if self._speak
            else None
        )
        parts: list[str] = []
        first_token_ms: int | None = None
        try:
            try:
                async for chunk in started.model.stream(messages):
                    if first_token_ms is None:
                        first_token_ms = self._elapsed_ms(since)
                    parts.append(chunk)
                    await self._send(AssistantTextDelta(turn_id=turn_id, text=chunk))
                    if speaker:
                        speaker.add(chunk)
            except ProviderError as error:
                await self._error("llm_failed", error.message)
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
            first_audio_ms = await speaker.finish() if speaker else None
            await self._send(
                TurnMetrics(
                    turn_id=turn_id,
                    first_token_ms=first_token_ms,
                    reply_ms=reply_ms,
                    first_audio_ms=first_audio_ms,
                )
            )
        finally:
            if speaker:
                await speaker.stop()

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


class _Speaker:
    """Speaks one reply while it streams in: each complete sentence goes to text-to-speech, one
    at a time and in order, and its audio to the client as soon as it is produced."""

    def __init__(
        self,
        tts: TextToSpeech,
        send: Send,
        send_audio: SendAudio,
        turn_id: str,
        elapsed_ms: Callable[[], int],
    ) -> None:
        self._tts = tts
        self._send = send
        self._send_audio = send_audio
        self._turn_id = turn_id
        self._elapsed_ms = elapsed_ms
        self._sentences = SentenceSplitter()
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._first_audio_ms: int | None = None
        self._task = asyncio.create_task(self._run())

    def add(self, text: str) -> None:
        for sentence in self._sentences.feed(text):
            self._queue.put_nowait(sentence)

    async def finish(self) -> int | None:
        """Speak the rest of the reply; return when the tutor's first audio was sent."""
        for sentence in self._sentences.flush():
            self._queue.put_nowait(sentence)
        self._queue.put_nowait(None)
        await asyncio.wait([self._task])
        return self._first_audio_ms

    async def stop(self) -> None:
        """Stop speaking (a no-op once finished)."""
        await _cancel(self._task)

    async def _run(self) -> None:
        try:
            while (sentence := await self._queue.get()) is not None:
                if text := speakable(sentence):
                    async for pcm in self._tts.synthesize(text):
                        await self._audio(pcm)
        except ProviderError as error:
            # The reply goes on as text only.
            await self._send(
                ErrorEvent(
                    code="tts_failed",
                    message=f"The tutor's voice failed. {error.message}",
                    retryable=True,
                )
            )
        except asyncio.CancelledError:
            if self._first_audio_ms is not None:
                with suppress(Exception):  # the socket may already be gone
                    await self._send(AssistantAudioDone(turn_id=self._turn_id, interrupted=True))
            raise
        if self._first_audio_ms is not None:
            await self._send(AssistantAudioDone(turn_id=self._turn_id))

    async def _audio(self, pcm: bytes) -> None:
        if self._first_audio_ms is None:
            self._first_audio_ms = self._elapsed_ms()
            await self._send(
                AssistantAudioStarted(turn_id=self._turn_id, sample_rate=OUTPUT_SAMPLE_RATE_HZ)
            )
        await self._send_audio(pcm)


async def _cancel(task: asyncio.Task[None]) -> None:
    task.cancel()
    # `wait` does not re-raise the task's CancelledError into the caller.
    await asyncio.wait([task])
