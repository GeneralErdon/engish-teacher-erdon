"""Speech-to-text over the OpenAI-compatible `/audio/transcriptions` API (official `openai`
SDK): Speaches locally, or any compatible server."""

import openai

from vt_api.adapters.openai_chat import provider_error
from vt_api.adapters.openai_models import base_url, model_status
from vt_contracts.speech import ModelStatus

LANGUAGE = "en"
"""The learner practises English: telling Whisper skips language detection (faster, and no
mistaking an accent for another language)."""


class OpenAISpeechToText:
    def __init__(self, client: openai.AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    async def transcribe(self, wav: bytes) -> str:
        try:
            result = await self._client.audio.transcriptions.create(
                model=self._model,
                file=("speech.wav", wav, "audio/wav"),
                language=LANGUAGE,
                response_format="json",
            )
        except openai.APIError as error:
            raise provider_error(error, base_url(self._client)) from error
        return result.text.strip()

    async def status(self) -> ModelStatus:
        return await model_status(self._client, self._model)
