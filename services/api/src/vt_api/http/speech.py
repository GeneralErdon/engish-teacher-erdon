"""`/v1/speech`: the voice settings, the models that can be downloaded, and whether speech
recognition and the tutor's voice are ready."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.routing import APIRoute

from vt_api.domain.speech import SpeechSettingsError
from vt_api.services.speech import SpeechService
from vt_contracts.speech import (
    DownloadRequest,
    SpeechModels,
    SpeechSettings,
    SpeechSettingsView,
    SpeechStatus,
    Voice,
    VoicePreview,
)


class _SpeechRoute(APIRoute):
    """Answers a `SpeechSettingsError` with its own status and message."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def translating(request: Request) -> Response:
            try:
                return await handler(request)
            except SpeechSettingsError as error:
                raise HTTPException(status_code=error.status, detail=error.message) from error

        return translating


router = APIRouter(prefix="/v1/speech", tags=["speech"], route_class=_SpeechRoute)


def _speech_service(request: Request) -> SpeechService:
    service: SpeechService = request.app.state.container.speech
    return service


Speech = Annotated[SpeechService, Depends(_speech_service)]


@router.get("/settings")
async def get_settings(speech: Speech) -> SpeechSettingsView:
    return await speech.view()


@router.put("/settings")
async def save_settings(body: SpeechSettings, speech: Speech) -> SpeechSettingsView:
    return await speech.save(body)


@router.get("/models")
async def get_models(speech: Speech) -> SpeechModels:
    return await speech.models()


@router.post("/models/{key}/download", status_code=202)
async def download_model(key: str, body: DownloadRequest, speech: Speech) -> SpeechModels:
    """Starts the download in the background; poll `GET /models` for its progress."""
    return await speech.download(key, body.activate)


@router.delete("/models/{key}/download", status_code=204)
async def cancel_download(key: str, speech: Speech) -> None:
    """Stops the download of `key`; nothing to do once it has ended, and 409 while another model
    downloads."""
    await speech.cancel_download(key)


@router.delete("/models/{key}", status_code=204)
async def uninstall_model(key: str, speech: Speech) -> None:
    await speech.uninstall(key)


@router.get("/voices")
async def get_voices(model: str, speech: Speech) -> list[Voice]:
    return await speech.voices(model)


@router.post(
    "/preview",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}}},
)
async def preview_voice(body: VoicePreview, speech: Speech) -> Response:
    """A short sentence in the chosen voice, as a WAV."""
    return Response(content=await speech.preview(body), media_type="audio/wav")


@router.get("/status")
async def speech_status(speech: Speech) -> SpeechStatus:
    """Whether each speech server answers and has the model a conversation would use: the
    selected one, or the default while the selected one is not installed. Speech-to-text for
    the learner's voice, text-to-speech for the tutor's."""
    return await speech.status()
