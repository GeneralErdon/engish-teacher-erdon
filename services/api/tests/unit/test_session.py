"""The conversation session with a scripted chat model and fake speech: no network,
deterministic timing."""

import asyncio
import itertools
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field, replace
from unittest.mock import AsyncMock, create_autospec

import pytest
from pydantic import SecretStr

from vt_api.adapters.speaches import SpeachesServer
from vt_api.domain.audio import duration_s
from vt_api.domain.llm import ChatMessage, LlmConfig, ProviderConfig, ProviderError
from vt_api.domain.speech import (
    EngineUnreachable,
    Recognition,
    SessionSpeech,
    VoiceChoice,
    transcription_timeout_s,
)
from vt_api.ports.llm import ChatModel
from vt_api.realtime.session import ConversationSession
from vt_api.services.learner import LearnerService
from vt_api.services.llm import LlmService
from vt_api.services.speech import SpeechService
from vt_contracts.speech import ModelStatus, SpeechSettings
from vt_contracts.ws import (
    AssistantAudioDone,
    AssistantAudioStarted,
    AssistantTextDelta,
    AssistantTextDone,
    Correction,
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


SPEECH = SessionSpeech(
    recognition=Recognition("openai", "whisper", "whisper"),
    voice=VoiceChoice("kokoro", "af_heart", 0.95),
    max_turn_s=120,
)
GPU_MODEL = "ggerganov/whisper.cpp/ggml-small.en-q8_0.bin"
GPU_PATH = f"models--ggerganov--whisper.cpp/snapshots/0123/{GPU_MODEL.rsplit('/', 1)[1]}"
ON_THE_GPU = replace(
    SPEECH,
    recognition=Recognition("whispercpp", GPU_MODEL, GPU_PATH),
    fallback=SPEECH.recognition,
)
GPU_UNAVAILABLE = (
    "whisper.cpp (GPU) is not running: Speaches transcribes this conversation. Start it with "
    "`just voice gpu`, or choose Speaches in Settings → Voice."
)
GPU_STOPPED = (
    "whisper.cpp (GPU) stopped answering: Speaches transcribes the rest of this conversation."
)
DEFAULTS = SpeechSettings(
    stt_model="whisper",
    stt_engine="openai",
    stt_gpu_model="ggerganov/whisper.cpp/ggml-small.en-q8_0.bin",
    tts_model="kokoro",
    tts_voice="af_heart",
    tts_speed=0.95,
    max_turn_s=120,
)


class SavedSpeech:
    """The saved speech settings; nothing saved means the defaults."""

    def __init__(self, saved: SpeechSettings | None = None) -> None:
        self.saved = saved

    async def load(self) -> SpeechSettings | None:
        return self.saved

    async def save(self, settings: SpeechSettings) -> None:
        self.saved = settings


@dataclass
class FakeStt:
    text: str = "I have went to the beach"
    error: ProviderError | None = None
    hold: asyncio.Event | None = None
    heard: list[bytes] = field(default_factory=list)
    asked: list[tuple[str, float]] = field(default_factory=list)
    """The model and timeout of each transcription."""

    async def transcribe(self, wav: bytes, model: str, timeout_s: float) -> str:
        self.heard.append(wav)
        self.asked.append((model, timeout_s))
        if self.hold:
            await self.hold.wait()
        if self.error:
            raise self.error
        return self.text

    async def status(self, model: str) -> ModelStatus:
        raise NotImplementedError


@dataclass
class FakeGpu:
    """The whisper.cpp server, as a conversation on it sees it: loaded when it started."""

    text: str = "I have gone to the beach"
    error: ProviderError | None = None
    hold: asyncio.Event | None = None
    asked: list[str] = field(default_factory=list)
    """The model path of each transcription."""

    async def running(self) -> bool:
        raise NotImplementedError

    async def load(self, model: str) -> None:
        raise NotImplementedError

    async def transcribe(self, wav: bytes, model: str, timeout_s: float) -> str:
        self.asked.append(model)
        if self.hold:
            await self.hold.wait()
        if self.error:
            raise self.error
        return self.text

    async def status(self, model: str) -> ModelStatus:
        raise NotImplementedError


@dataclass
class FakeTts:
    """Says each word of a sentence as one chunk of "audio" (the word's bytes)."""

    error: ProviderError | None = None
    fail_after: int = 0
    """Words spoken before `error`."""
    hold: asyncio.Event | None = None
    """When set, waits on it after the first word."""
    said: list[str] = field(default_factory=list)
    voices: list[VoiceChoice] = field(default_factory=list)

    async def synthesize(self, text: str, voice: VoiceChoice) -> AsyncIterator[bytes]:
        self.said.append(text)
        self.voices.append(voice)
        for index, word in enumerate(text.split()):
            if self.error and index == self.fail_after:
                raise self.error
            if index == 1 and self.hold:
                await self.hold.wait()
            yield word.encode()

    async def status(self, model: str) -> ModelStatus:
        raise NotImplementedError


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
def audio() -> list[bytes]:
    return []


@pytest.fixture
def stt() -> FakeStt:
    return FakeStt()


@pytest.fixture
def tts() -> FakeTts:
    return FakeTts()


@pytest.fixture
def gpu() -> FakeGpu:
    return FakeGpu()


@pytest.fixture
def saved_speech() -> SavedSpeech:
    return SavedSpeech()


@pytest.fixture
def speech(saved_speech: SavedSpeech, stt: FakeStt, tts: FakeTts, gpu: FakeGpu) -> SpeechService:
    """Without the models folder, the GPU engine is unusable: tests put a conversation on it
    through `for_session`."""
    return SpeechService(
        repository=saved_speech,
        stt=stt,
        tts=tts,
        recognition_server=create_autospec(SpeachesServer, instance=True),
        voice_server=create_autospec(SpeachesServer, instance=True),
        files=None,
        defaults=DEFAULTS,
        gpu_stt=gpu,
    )


@pytest.fixture
def send_yields() -> bool:
    """Whether sending an event lets other tasks run first, as a real socket can. Tests that
    race two tasks across a send turn it on with `@pytest.mark.parametrize`."""
    return False


@pytest.fixture
def session(
    chat: ScriptedChat,
    events: list[ServerEvent],
    audio: list[bytes],
    learner_service: LearnerService,
    speech: SpeechService,
    send_yields: bool,
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
        if send_yields:
            await asyncio.sleep(0)
        events.append(event)

    async def send_audio(pcm: bytes) -> None:
        audio.append(pcm)

    # Each clock read advances 100 ms, so latencies are predictable.
    return ConversationSession(
        send=send,
        send_audio=send_audio,
        llm=llm,
        learner=learner_service,
        speech=speech,
        clock=lambda: next(ticks) / 10,
    )


async def _settle() -> None:
    for _ in range(50):
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


HALF_A_SECOND = bytes(16_000)


def _speak(session: ConversationSession, pcm: bytes = HALF_A_SECOND) -> None:
    for start in range(0, len(pcm), 640):
        session.audio(pcm[start : start + 640])


async def test_a_spoken_turn(
    session: ConversationSession, stt: FakeStt, events: list[ServerEvent]
) -> None:
    await session.handle(SessionStart())
    _speak(session)
    await session.handle(InputCommit())
    await _settle()

    [transcript] = _of(TranscriptFinal, events)
    assert (transcript.text, transcript.source) == ("I have went to the beach", "voice")
    assert transcript.stt_ms == 100  # one clock tick
    assert stt.heard[0].startswith(b"RIFF")
    assert stt.asked == [
        (SPEECH.recognition.server_model, transcription_timeout_s(duration_s(len(HALF_A_SECOND))))
    ]
    assert len(_of(Correction, events)) == 1
    assert len(_of(AssistantTextDone, events)) == 1


async def test_each_turn_starts_with_fresh_audio(
    session: ConversationSession, stt: FakeStt
) -> None:
    await session.handle(SessionStart())
    _speak(session)
    await session.handle(InputCommit())
    _speak(session)
    await session.handle(InputCommit())
    await _settle()

    assert [len(wav) for wav in stt.heard] == [len(stt.heard[0])] * 2


async def test_a_recording_must_be_speech_length(
    session: ConversationSession, events: list[ServerEvent]
) -> None:
    await session.handle(SessionStart())
    _speak(session, bytes(6_400))  # 0.2 s
    await session.handle(InputCommit())

    assert [e.code for e in _of(ErrorEvent, events)] == ["audio_too_short"]
    assert _of(TranscriptFinal, events) == []


async def test_a_long_turn_is_cut_not_lost(
    session: ConversationSession,
    saved_speech: SavedSpeech,
    speech: SpeechService,
    stt: FakeStt,
    events: list[ServerEvent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved_speech.saved = DEFAULTS.model_copy(update={"max_turn_s": 30})
    recorded: list[float] = []
    transcribe = speech.transcribe

    async def spy(wav: bytes, audio_s: float, recognition: Recognition) -> str:
        recorded.append(audio_s)
        return await transcribe(wav, audio_s, recognition)

    monkeypatch.setattr(speech, "transcribe", spy)
    await session.handle(SessionStart())
    _speak(session, bytes(32_000 * 31))
    await session.handle(InputCommit())
    await _settle()

    [transcript] = _of(TranscriptFinal, events)
    assert transcript.cut is True
    assert _of(ErrorEvent, events) == []
    assert recorded == [30.0]
    assert stt.asked == [("whisper", transcription_timeout_s(30.0))]
    assert len(stt.heard[0]) == 44 + 32_000 * 30  # a WAV header, then exactly 30 s


async def test_a_chunk_across_the_limit_is_trimmed_to_it(
    session: ConversationSession,
    saved_speech: SavedSpeech,
    stt: FakeStt,
    events: list[ServerEvent],
) -> None:
    saved_speech.saved = DEFAULTS.model_copy(update={"max_turn_s": 30})
    await session.handle(SessionStart())
    session.audio(bytes(32_000 * 29 + 16_000))  # 29.5 s
    session.audio(bytes(32_000))  # 1 s, of which 0.5 s fits
    await session.handle(InputCommit())
    await _settle()

    assert len(stt.heard[0]) == 44 + 32_000 * 30
    assert _of(TranscriptFinal, events)[0].cut is True


async def test_a_sample_split_across_chunks_stays_aligned(
    session: ConversationSession, stt: FakeStt, events: list[ServerEvent]
) -> None:
    await session.handle(SessionStart())
    session.audio(bytes(16_000) + bytes([1, 2, 3]))
    session.audio(bytes([4, 5, 6]))
    await session.handle(InputCommit())
    await _settle()

    assert stt.heard[0][-6:] == bytes([1, 2, 3, 4, 5, 6])
    assert _of(TranscriptFinal, events)[0].cut is False


async def test_the_cut_lands_on_the_limit_after_a_split_sample(
    session: ConversationSession, saved_speech: SavedSpeech, stt: FakeStt
) -> None:
    saved_speech.saved = DEFAULTS.model_copy(update={"max_turn_s": 30})
    await session.handle(SessionStart())
    session.audio(bytes(31_999))  # an odd count: the buffer is mid-sample
    session.audio(bytes(32_000 * 30))
    await session.handle(InputCommit())
    await _settle()

    assert len(stt.heard[0]) == 44 + 32_000 * 30


async def test_audio_after_the_cut_is_ignored(
    session: ConversationSession, saved_speech: SavedSpeech, stt: FakeStt
) -> None:
    saved_speech.saved = DEFAULTS.model_copy(update={"max_turn_s": 30})
    await session.handle(SessionStart())
    session.audio(bytes(32_000 * 29 + 16_000))
    session.audio(bytes(32_000))  # cut at 30 s
    session.audio(bytes(640))  # would fit if the buffer had room: it has none
    session.audio(bytes(32_000 * 29))
    await session.handle(InputCommit())
    await _settle()

    assert len(stt.heard[0]) == 44 + 32_000 * 30


async def test_a_turn_within_the_limit_is_not_cut(
    session: ConversationSession, events: list[ServerEvent]
) -> None:
    await session.handle(SessionStart())
    _speak(session)
    await session.handle(InputCommit())
    await _settle()

    assert _of(TranscriptFinal, events)[0].cut is False


async def test_audio_sent_before_start_does_not_leak_into_the_next_turn(
    session: ConversationSession, events: list[ServerEvent], stt: FakeStt
) -> None:
    _speak(session, bytes(32_000 * 121))
    await session.handle(InputCommit())  # not started: the audio is dropped
    await session.handle(SessionStart())
    _speak(session)
    await session.handle(InputCommit())
    await _settle()

    assert [e.code for e in _of(ErrorEvent, events)] == ["not_started"]
    assert _of(TranscriptFinal, events)[0].cut is False


async def test_session_uses_the_chosen_voice(
    session: ConversationSession, saved_speech: SavedSpeech, tts: FakeTts
) -> None:
    saved_speech.saved = DEFAULTS.model_copy(update={"tts_voice": "bf_emma", "tts_speed": 1.2})
    await session.handle(SessionStart(speak=True))
    await session.handle(InputText(text="Hello"))
    await _settle()

    assert tts.said
    assert tts.voices == [VoiceChoice("kokoro", "bf_emma", 1.2)] * len(tts.said)


async def test_missing_model_warns_at_start(
    session: ConversationSession, speech: SpeechService, events: list[ServerEvent]
) -> None:
    speech.for_session = AsyncMock(  # type: ignore[method-assign]
        return_value=replace(SPEECH, missing=("recognition", "voice"))
    )
    await session.handle(SessionStart())

    first, second = _of(ErrorEvent, events)
    assert (first.code, first.retryable) == ("speech_model_missing", True)
    assert "speech recognition" in first.message
    assert "default is used" in first.message
    assert "Settings → Voice" in first.message
    assert "the tutor's voice" in second.message
    assert isinstance(events[0], SessionReady)  # the session still starts


async def test_nothing_is_missing_by_default(
    session: ConversationSession, events: list[ServerEvent]
) -> None:
    await session.handle(SessionStart())

    assert _of(ErrorEvent, events) == []


async def test_speech_recognition_failures(
    session: ConversationSession, stt: FakeStt, events: list[ServerEvent]
) -> None:
    await session.handle(SessionStart())
    stt.error = ProviderError("connection", "Could not connect to http://localhost:8000/v1.")
    _speak(session)
    await session.handle(InputCommit())
    await _settle()
    stt.error, stt.text = None, ""
    _speak(session)
    await session.handle(InputCommit())
    await _settle()

    errors = _of(ErrorEvent, events)
    assert [e.code for e in errors] == ["stt_failed", "no_speech"]
    assert errors[0].message.endswith("Could not connect to http://localhost:8000/v1.")


async def test_audio_before_start_is_rejected(
    session: ConversationSession, events: list[ServerEvent]
) -> None:
    _speak(session)
    await session.handle(InputCommit())

    assert [e.code for e in _of(ErrorEvent, events)] == ["not_started"]


async def test_ending_stops_a_transcription(
    session: ConversationSession, stt: FakeStt, events: list[ServerEvent]
) -> None:
    stt.hold = asyncio.Event()
    await session.handle(SessionStart())
    _speak(session)
    await session.handle(InputCommit())
    await _settle()

    await session.handle(SessionEnd())
    stt.hold.set()
    await _settle()

    assert _of(TranscriptFinal, events) == []


async def test_the_tutor_speaks_each_sentence_as_it_is_written(
    session: ConversationSession,
    chat: ScriptedChat,
    tts: FakeTts,
    events: list[ServerEvent],
    audio: list[bytes],
) -> None:
    chat.reply = ("Nice! ", "What did you do?")
    chat.hold = asyncio.Event()
    await session.handle(SessionStart(speak=True))
    await session.handle(InputText(text="I have went to the beach"))
    await _settle()

    # The first sentence is spoken while the model is still writing the second.
    assert (tts.said, audio) == (["Nice!"], [b"Nice!"])
    chat.hold.set()
    await _settle()

    assert tts.said == ["Nice!", "What did you do?"]
    assert tts.voices == [SPEECH.voice, SPEECH.voice]
    assert audio == [b"Nice!", b"What", b"did", b"you", b"do?"]
    kinds = [event.type for event in events if event.type.startswith(("assistant.", "turn."))]
    assert kinds == [
        "assistant.text.delta",
        "assistant.audio.started",
        "assistant.text.delta",
        "assistant.text.done",
        "assistant.audio.done",
        "turn.metrics",
    ]
    assert _of(AssistantAudioStarted, events) == [
        AssistantAudioStarted(turn_id="t1", sample_rate=24_000)
    ]
    assert _of(AssistantAudioDone, events) == [AssistantAudioDone(turn_id="t1")]
    [metrics] = _of(TurnMetrics, events)
    assert metrics.first_audio_ms is not None
    assert metrics.first_token_ms is not None
    assert metrics.first_audio_ms > metrics.first_token_ms


async def test_replies_are_silent_unless_the_learner_asks(
    session: ConversationSession, tts: FakeTts, events: list[ServerEvent], audio: list[bytes]
) -> None:
    await session.handle(SessionStart())
    await session.handle(InputText(text="Hello"))
    await _settle()

    assert (tts.said, audio, _of(AssistantAudioStarted, events)) == ([], [], [])
    assert _of(TurnMetrics, events)[0].first_audio_ms is None


async def test_the_voice_can_be_switched_on_during_the_session(
    session: ConversationSession, tts: FakeTts
) -> None:
    assert await session.handle(SessionUpdate(speak=True))  # before start: kept for later
    await session.handle(SessionStart())
    await session.handle(InputText(text="Hello"))
    await _settle()
    await session.handle(SessionUpdate(speak=True))
    await session.handle(InputText(text="Hello again"))
    await _settle()

    assert tts.said == ["Nice!", "What did you do?"]  # the second reply only


async def test_interrupting_stops_the_voice(
    session: ConversationSession, tts: FakeTts, events: list[ServerEvent], audio: list[bytes]
) -> None:
    tts.hold = asyncio.Event()
    await session.handle(SessionStart(speak=True))
    await session.handle(InputText(text="Hello"))
    await _settle()

    await session.handle(InputInterrupt())
    tts.hold.set()
    await _settle()

    assert audio == [b"Nice!", b"What"]
    assert _of(AssistantAudioDone, events) == [AssistantAudioDone(turn_id="t1", interrupted=True)]
    assert _of(TurnMetrics, events) == []


async def test_interrupting_while_writing_stops_the_voice_too(
    session: ConversationSession, chat: ScriptedChat, events: list[ServerEvent]
) -> None:
    chat.reply = ("Nice! ", "What did you do?")
    chat.hold = asyncio.Event()
    await session.handle(SessionStart(speak=True))
    await session.handle(InputText(text="Hello"))
    await _settle()

    await session.handle(InputInterrupt())

    assert _of(AssistantTextDone, events)[-1].interrupted is True
    assert _of(AssistantAudioDone, events) == [AssistantAudioDone(turn_id="t1", interrupted=True)]


@pytest.mark.parametrize(("fail_after", "spoken"), [(0, False), (1, True)])
async def test_a_voice_failure_leaves_the_text_reply(
    session: ConversationSession,
    chat: ScriptedChat,
    tts: FakeTts,
    events: list[ServerEvent],
    fail_after: int,
    spoken: bool,
) -> None:
    tts.error = ProviderError("connection", "Could not connect to http://localhost:8000/v1.")
    tts.fail_after = fail_after
    chat.reply = ("Nice to meet you!",)
    await session.handle(SessionStart(speak=True))
    await session.handle(InputText(text="Hello"))
    await _settle()

    [error] = _of(ErrorEvent, events)
    assert error.code == "tts_failed"
    assert error.message.endswith("Could not connect to http://localhost:8000/v1.")
    assert _of(AssistantTextDone, events)[0].text == "Nice to meet you!"
    assert len(_of(AssistantAudioDone, events)) == int(spoken)
    assert (_of(TurnMetrics, events)[0].first_audio_ms is not None) == spoken


async def test_a_failed_reply_is_not_spoken(
    session: ConversationSession, chat: ScriptedChat, tts: FakeTts
) -> None:
    chat.reply_error = ProviderError("auth", "nope")
    await session.handle(SessionStart(speak=True))
    await session.handle(InputText(text="Hello"))
    await _settle()

    assert tts.said == []


async def test_interrupting_before_the_voice_starts(
    session: ConversationSession, chat: ScriptedChat, events: list[ServerEvent]
) -> None:
    chat.hold = asyncio.Event()  # after "Nice", before the sentence ends
    await session.handle(SessionStart(speak=True))
    await session.handle(InputText(text="Hello"))
    await _settle()

    await session.handle(InputInterrupt())

    assert _of(AssistantAudioStarted, events) == []
    assert _of(AssistantAudioDone, events) == []


async def test_only_words_are_spoken(
    session: ConversationSession, chat: ScriptedChat, tts: FakeTts
) -> None:
    chat.reply = ("**Nice!** ", "🙂")
    await session.handle(SessionStart(speak=True))
    await session.handle(InputText(text="Hello"))
    await _settle()

    assert tts.said == ["Nice!"]


# ---------------------------------------------------------------- the speech recognition engine


def _on_the_gpu(speech: SpeechService) -> None:
    speech.for_session = AsyncMock(return_value=ON_THE_GPU)  # type: ignore[method-assign]


async def _say(session: ConversationSession) -> None:
    _speak(session)
    await session.handle(InputCommit())


async def test_start_warns_when_the_engine_is_unavailable(
    session: ConversationSession, saved_speech: SavedSpeech, events: list[ServerEvent]
) -> None:
    """Review Focus 4: whisper.cpp is saved, but the GPU engine is unusable (no models
    folder here)."""
    saved_speech.saved = DEFAULTS.model_copy(update={"stt_engine": "whispercpp"})

    await session.handle(SessionStart())

    assert isinstance(events[0], SessionReady)  # the session still starts
    assert _of(ErrorEvent, events) == [
        ErrorEvent(code="speech_engine_unavailable", message=GPU_UNAVAILABLE, retryable=True)
    ]


async def test_a_turn_on_the_gpu(
    session: ConversationSession,
    speech: SpeechService,
    gpu: FakeGpu,
    stt: FakeStt,
    events: list[ServerEvent],
) -> None:
    _on_the_gpu(speech)
    await session.handle(SessionStart())
    await _say(session)
    await _settle()

    assert gpu.asked == [GPU_PATH]
    assert stt.asked == []
    assert [t.text for t in _of(TranscriptFinal, events)] == ["I have gone to the beach"]
    assert _of(ErrorEvent, events) == []


async def test_gpu_unreachable_mid_conversation_switches_to_speaches_once(
    session: ConversationSession,
    speech: SpeechService,
    gpu: FakeGpu,
    stt: FakeStt,
    events: list[ServerEvent],
) -> None:
    """Review Focus 2: the GPU server died after the conversation started."""
    _on_the_gpu(speech)
    gpu.error = EngineUnreachable("http://localhost:8002/v1")
    await session.handle(SessionStart())
    await _say(session)
    await _settle()
    await _say(session)
    await _settle()

    assert gpu.asked == [GPU_PATH]  # the second turn goes straight to Speaches
    assert [model for model, _ in stt.asked] == ["whisper", "whisper"]
    assert [t.text for t in _of(TranscriptFinal, events)] == ["I have went to the beach"] * 2
    assert _of(ErrorEvent, events) == [
        ErrorEvent(code="speech_engine_unavailable", message=GPU_STOPPED, retryable=True)
    ]


@pytest.mark.parametrize("send_yields", [True])
async def test_two_turns_losing_the_gpu_together_warn_once(
    session: ConversationSession,
    speech: SpeechService,
    gpu: FakeGpu,
    stt: FakeStt,
    events: list[ServerEvent],
) -> None:
    """The warning's send yields, so the second turn runs while the first one warns: only a
    switch made before that send keeps it from warning too."""
    _on_the_gpu(speech)
    gpu.error = EngineUnreachable("http://localhost:8002/v1")
    gpu.hold = asyncio.Event()
    await session.handle(SessionStart())
    await _say(session)
    await _say(session)
    await _settle()  # both turns wait on the GPU

    gpu.hold.set()
    await _settle()

    assert gpu.asked == [GPU_PATH, GPU_PATH]
    assert len(stt.asked) == 2
    assert len(_of(TranscriptFinal, events)) == 2
    assert [e.code for e in _of(ErrorEvent, events)] == ["speech_engine_unavailable"]


async def test_gpu_read_timeout_is_stt_failed(
    session: ConversationSession,
    speech: SpeechService,
    gpu: FakeGpu,
    stt: FakeStt,
    events: list[ServerEvent],
) -> None:
    """Review Focus 2: a server that is up but slow, or answers with an error, is no reason
    to leave it."""
    _on_the_gpu(speech)
    gpu.error = ProviderError("connection", "http://localhost:8002/v1 did not answer in time.")
    await session.handle(SessionStart())
    await _say(session)
    await _settle()
    gpu.error = None
    await _say(session)
    await _settle()

    assert gpu.asked == [GPU_PATH, GPU_PATH]
    assert stt.asked == []
    [error] = _of(ErrorEvent, events)
    assert (error.code, error.retryable) == ("stt_failed", True)
    assert error.message.endswith("did not answer in time.")
    assert len(_of(TranscriptFinal, events)) == 1


async def test_speaches_unreachable_is_stt_failed(
    session: ConversationSession, stt: FakeStt, events: list[ServerEvent]
) -> None:
    """Speaches has no fallback: the turn fails, and the next one tries it again."""
    stt.error = EngineUnreachable("http://localhost:8000/v1")
    await session.handle(SessionStart())
    await _say(session)
    await _settle()

    assert [e.code for e in _of(ErrorEvent, events)] == ["stt_failed"]
