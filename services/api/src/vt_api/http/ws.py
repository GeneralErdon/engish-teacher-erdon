"""`/ws/session`: the realtime conversation (protocol: `vt_contracts.ws`).

Text frames carry JSON events; binary frames carry audio: the microphone from the client (PCM16,
mono, 16 kHz), the tutor's voice from the server (PCM16, mono, 24 kHz).
"""

import asyncio
from contextlib import suppress
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from vt_api.ports.speech import SpeechToText, TextToSpeech
from vt_api.realtime.session import ConversationSession, Send
from vt_api.services.learner import LearnerService
from vt_api.services.llm import LlmService
from vt_contracts.ws import CLIENT_EVENT, ErrorEvent, ServerEvent

router = APIRouter(tags=["realtime"])


def origin_allowed(websocket: WebSocket, allowed: frozenset[str]) -> bool:
    """Browsers apply no CORS to WebSockets, so any page could open this socket and spend the
    learner's API credits. Allow the app's own origins, the page the api serves itself, and
    clients that send no Origin (not a browser)."""
    origin = websocket.headers.get("origin")
    if origin is None or origin in allowed:
        return True
    return urlsplit(origin).netloc == websocket.headers.get("host")


@router.websocket("/ws/session")
async def session_socket(websocket: WebSocket) -> None:
    state = websocket.app.state
    if not origin_allowed(websocket, state.allowed_origins):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()

    lock = asyncio.Lock()

    async def send(event: ServerEvent) -> None:
        # Replies, voice and corrections run in parallel; one frame at a time on the socket.
        async with lock:
            await websocket.send_text(event.model_dump_json())

    async def send_audio(pcm: bytes) -> None:
        async with lock:
            await websocket.send_bytes(pcm)

    llm: LlmService = state.container.llm
    learner: LearnerService = state.container.learner
    stt: SpeechToText = state.container.stt
    tts: TextToSpeech = state.container.tts
    session = ConversationSession(
        send=send,
        send_audio=send_audio,
        llm=llm,
        learner=learner,
        stt=stt,
        tts=tts,
        speech=state.container.session_speech,
    )
    try:
        # The client may go away while a reply is being sent: that ends the session too.
        with suppress(WebSocketDisconnect):
            await _serve(websocket, session, send)
    finally:
        await session.close()


async def _serve(websocket: WebSocket, session: ConversationSession, send: Send) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        if (audio := message.get("bytes")) is not None:
            session.audio(audio)
            continue
        try:
            event = CLIENT_EVENT.validate_json(message.get("text") or "")
        except ValidationError as error:
            await send(ErrorEvent(code="bad_event", message=str(error), retryable=False))
            continue
        if not await session.handle(event):
            await websocket.close()
            return
