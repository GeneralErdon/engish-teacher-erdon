"""`/ws/session`: the realtime conversation (protocol: `vt_contracts.ws`)."""

import asyncio
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from vt_api.realtime.session import ConversationSession
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
        # Replies and corrections run in parallel; one frame at a time on the socket.
        async with lock:
            await websocket.send_text(event.model_dump_json())

    llm: LlmService = state.container.llm
    learner: LearnerService = state.container.learner
    session = ConversationSession(send=send, llm=llm, learner=learner)
    try:
        while True:
            message = await websocket.receive_text()
            try:
                event = CLIENT_EVENT.validate_json(message)
            except ValidationError as error:
                await send(ErrorEvent(code="bad_event", message=str(error), retryable=False))
                continue
            if not await session.handle(event):
                await websocket.close()
                break
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()
