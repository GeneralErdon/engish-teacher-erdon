"""`/v1/speech`: is speech-to-text ready?"""

from fastapi import APIRouter, Request

from vt_api.ports.speech import SpeechToText
from vt_contracts.speech import SpeechStatus

router = APIRouter(prefix="/v1/speech", tags=["speech"])


@router.get("/status")
async def speech_status(request: Request) -> SpeechStatus:
    """Whether the speech-to-text server answers and has the configured model."""
    speech: SpeechToText = request.app.state.container.speech
    return await speech.status()
