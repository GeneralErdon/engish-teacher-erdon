"""`/v1/speech`: are speech recognition and the tutor's voice ready?"""

import asyncio

from fastapi import APIRouter, Request

from vt_api.ports.speech import SpeechToText, TextToSpeech
from vt_contracts.speech import SpeechStatus

router = APIRouter(prefix="/v1/speech", tags=["speech"])


@router.get("/status")
async def speech_status(request: Request) -> SpeechStatus:
    """Whether each speech server answers and has its model: speech-to-text for the learner's
    voice, text-to-speech for the tutor's."""
    stt: SpeechToText = request.app.state.container.stt
    tts: TextToSpeech = request.app.state.container.tts
    recognition, synthesis = await asyncio.gather(stt.status(), tts.status())
    return SpeechStatus(recognition=recognition, synthesis=synthesis)
