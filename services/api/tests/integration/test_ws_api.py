"""`/ws/session` end to end: real session, service and adapters; the providers are faked at the
HTTP transport (OpenAI-compatible servers answering with SSE streams, JSON and raw PCM)."""

import json

import httpx2
import openai
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from vt_api.adapters.chat_factory import SdkChatModelFactory
from vt_api.adapters.openai_stt import OpenAISpeechToText
from vt_api.adapters.openai_tts import OpenAITextToSpeech
from vt_api.adapters.sql.database import Database
from vt_api.adapters.sql.llm_config import SqlLlmConfigRepository
from vt_api.config import Settings
from vt_api.container import Container
from vt_api.domain.llm import environment_config
from vt_api.main import create_app
from vt_api.services.learner import LearnerService
from vt_api.services.llm import LlmService
from vt_contracts.ws import SERVER_EVENT, ServerEvent, TurnMetrics

VOICE = b"\x01\x00" * 2_400  # 0.1 s of PCM16 at 24 kHz

CORRECTION = {
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


def _sse(*texts: str) -> httpx2.Response:
    chunks = [
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "m",
            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
        }
        for text in texts
    ]
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
    return httpx2.Response(200, text=body, headers={"content-type": "text/event-stream"})


def _provider(request: httpx2.Request) -> httpx2.Response:
    if request.url.path.endswith("/audio/transcriptions"):
        return httpx2.Response(200, json={"text": "I have went to the beach"})
    if request.url.path.endswith("/audio/speech"):
        return httpx2.Response(200, content=VOICE, headers={"content-type": "audio/pcm"})
    if request.url.path.endswith("/models"):
        model = {"id": "whisper", "object": "model", "created": 0, "owned_by": "speaches"}
        return httpx2.Response(200, json={"object": "list", "data": [model]})
    system = json.loads(request.content)["messages"][0]["content"]
    if "corrections as JSON" in system:
        return _sse(json.dumps(CORRECTION))
    return _sse("Nice", "! What did you do?")


@pytest.fixture
def client(database: Database, learner_service: LearnerService) -> TestClient:
    transport = httpx2.MockTransport(_provider)
    chat_models = SdkChatModelFactory(
        openai_http=httpx2.AsyncClient(transport=transport),
        anthropic_http=httpx2.AsyncClient(transport=transport),
        max_retries=0,
    )
    environment = environment_config(
        kind="openai_compatible", base_url="http://llm/v1", model="m", api_key=SecretStr("")
    )
    llm = LlmService(
        repository=SqlLlmConfigRepository(database),
        chat_models=chat_models,
        environment=environment,
    )

    def speech_client(base_url: str) -> openai.AsyncOpenAI:
        return openai.AsyncOpenAI(
            api_key="none",
            base_url=base_url,
            http_client=httpx2.AsyncClient(transport=transport),
            max_retries=0,
        )

    container = Container(
        llm=llm,
        learner=learner_service,
        stt=OpenAISpeechToText(speech_client("http://stt/v1"), "whisper"),
        tts=OpenAITextToSpeech(speech_client("http://tts/v1"), "kokoro", "af_heart", 1.0),
    )
    return TestClient(create_app(Settings(_env_file=None), container=container))


def _receive(ws: WebSocketTestSession, count: int) -> list[ServerEvent]:
    return [SERVER_EVENT.validate_json(ws.receive_text()) for _ in range(count)]


def _receive_until(ws: WebSocketTestSession, kind: str) -> list[ServerEvent | bytes]:
    """Events and audio frames, up to and including the first event of type `kind`."""
    frames: list[ServerEvent | bytes] = []
    while True:
        message = ws.receive()
        if (pcm := message.get("bytes")) is not None:
            frames.append(pcm)
            continue
        event = SERVER_EVENT.validate_json(message["text"])
        frames.append(event)
        if event.type == kind:
            return frames


def test_a_conversation_over_the_socket(client: TestClient) -> None:
    with client.websocket_connect("/ws/session", headers={"origin": "tauri://localhost"}) as ws:
        ws.send_text(json.dumps({"type": "session.start", "v": 1}))
        [ready] = _receive(ws, 1)
        ws.send_text(json.dumps({"type": "input.text", "v": 1, "text": "I have went to the beach"}))
        # transcript, 2 deltas, done, metrics, correction: order between the last ones varies.
        events = _receive(ws, 6)
        ws.send_text(json.dumps({"type": "session.end", "v": 1}))

    assert ready.type == "session.ready"
    kinds = [event.type for event in events]
    assert kinds[0] == "transcript.final"
    assert sorted(kinds[1:]) == sorted(
        ["assistant.text.delta"] * 2 + ["assistant.text.done", "turn.metrics", "correction"]
    )
    correction = next(event for event in events if event.type == "correction")
    assert correction.model_dump()["corrected"] == "I went to the beach"


def test_a_spoken_turn(client: TestClient) -> None:
    half_a_second = bytes(16_000)  # PCM16 at 16 kHz
    with client.websocket_connect("/ws/session") as ws:
        ws.send_text(json.dumps({"type": "session.start", "v": 1}))
        _receive(ws, 1)
        for start in range(0, len(half_a_second), 640):  # 20 ms frames
            ws.send_bytes(half_a_second[start : start + 640])
        ws.send_text(json.dumps({"type": "input.commit", "v": 1}))
        [transcript] = _receive(ws, 1)
        ws.send_text(json.dumps({"type": "session.end", "v": 1}))

    assert transcript.model_dump() | {"stt_ms": 0} == {
        "v": 1,
        "type": "transcript.final",
        "turn_id": "t1",
        "text": "I have went to the beach",
        "source": "voice",
        "stt_ms": 0,
    }


def test_the_tutor_speaks(client: TestClient) -> None:
    with client.websocket_connect("/ws/session") as ws:
        ws.send_text(json.dumps({"type": "session.start", "v": 1, "speak": True}))
        _receive(ws, 1)
        ws.send_text(json.dumps({"type": "input.text", "v": 1, "text": "Hello"}))
        frames = _receive_until(ws, "turn.metrics")
        ws.send_text(json.dumps({"type": "session.end", "v": 1}))

    kinds = [frame if isinstance(frame, bytes) else frame.type for frame in frames]
    started = kinds.index("assistant.audio.started")
    done = kinds.index("assistant.audio.done")
    voice = kinds[started + 1 : done]
    # Two sentences, "Nice!" and "What did you do?": two clips, only audio between the brackets.
    assert b"".join(frame for frame in voice if isinstance(frame, bytes)) == VOICE * 2
    assert all(isinstance(frame, bytes) or frame.startswith("assistant.text") for frame in voice)
    metrics = frames[-1]
    assert isinstance(metrics, TurnMetrics)
    assert metrics.first_audio_ms is not None


def test_invalid_events_get_an_error_and_the_session_goes_on(client: TestClient) -> None:
    with client.websocket_connect("/ws/session") as ws:
        ws.send_text('{"type": "dance", "v": 1}')
        [error] = _receive(ws, 1)
        ws.send_text(json.dumps({"type": "input.text", "v": 1, "text": "Hi"}))
        [not_started] = _receive(ws, 1)

    assert error.model_dump()["code"] == "bad_event"
    assert not_started.model_dump()["code"] == "not_started"


@pytest.mark.parametrize("origin", ["https://evil.example", "http://localhost:9999"])
def test_other_websites_cannot_connect(client: TestClient, origin: str) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect("/ws/session", headers={"origin": origin}) as ws,
    ):
        ws.receive_text()

    assert closed.value.code == 1008


def test_the_page_the_api_serves_may_connect(client: TestClient) -> None:
    # The test client's Host header is "testserver".
    with client.websocket_connect("/ws/session", headers={"origin": "http://testserver"}) as ws:
        ws.send_text(json.dumps({"type": "session.start", "v": 1}))
        [ready] = _receive(ws, 1)

    assert ready.type == "session.ready"


def test_the_schema_describes_the_socket_events(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    events = schema["components"]["schemas"]
    assert set(events["ClientEvent"]["discriminator"]["mapping"]) == {
        "session.start",
        "session.update",
        "input.text",
        "input.commit",
        "input.interrupt",
        "session.end",
    }
    assert "correction" in events["ServerEvent"]["discriminator"]["mapping"]
    assert client.get("/openapi.json").json() == schema  # built once, then cached


def test_speech_status(client: TestClient) -> None:
    status = client.get("/v1/speech/status").json()

    assert status["recognition"] == {
        "base_url": "http://stt/v1",
        "model": "whisper",
        "reachable": True,
        "model_ready": True,
        "detail": None,
    }
    # The fake server lists only "whisper".
    assert status["synthesis"] == {
        "base_url": "http://tts/v1",
        "model": "kokoro",
        "reachable": True,
        "model_ready": False,
        "detail": "The model kokoro is not downloaded.",
    }
