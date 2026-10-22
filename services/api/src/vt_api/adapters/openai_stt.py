"""Speech-to-text over the OpenAI-compatible `/audio/transcriptions` API (official `openai`
SDK): Speaches locally, or any compatible server."""

import openai

from vt_api.adapters.openai_chat import provider_error
from vt_contracts.speech import SpeechStatus

LANGUAGE = "en"
"""The learner practises English: telling Whisper skips language detection (faster, and no
mistaking an accent for another language)."""


class OpenAISpeechToText:
    def __init__(self, client: openai.AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def _base_url(self) -> str:
        return str(self._client.base_url).rstrip("/")

    async def transcribe(self, wav: bytes) -> str:
        try:
            result = await self._client.audio.transcriptions.create(
                model=self._model,
                file=("speech.wav", wav, "audio/wav"),
                language=LANGUAGE,
                response_format="json",
            )
        except openai.APIError as error:
            raise provider_error(error, self._base_url) from error
        return result.text.strip()

    async def status(self) -> SpeechStatus:
        status = SpeechStatus(
            base_url=self._base_url, model=self._model, reachable=False, model_ready=False
        )
        try:
            models = [model.id async for model in self._client.models.list()]
        except openai.APIError as error:
            return status.model_copy(
                update={"detail": provider_error(error, self._base_url).message}
            )
        if self._model not in models:
            return status.model_copy(
                update={"reachable": True, "detail": f"The model {self._model} is not downloaded."}
            )
        return status.model_copy(update={"reachable": True, "model_ready": True})
