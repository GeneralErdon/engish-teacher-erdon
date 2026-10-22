"""Text-to-speech over the OpenAI-compatible `/audio/speech` API (official `openai` SDK):
Kokoro in Speaches locally, Kokoro-FastAPI, or any compatible server that streams raw PCM at
Kokoro's 24 kHz."""

from collections.abc import AsyncIterator

import openai

from vt_api.adapters.openai_chat import provider_error
from vt_api.adapters.openai_models import base_url, model_status
from vt_contracts.audio import SAMPLE_WIDTH_BYTES
from vt_contracts.speech import ModelStatus


class OpenAITextToSpeech:
    def __init__(self, client: openai.AsyncOpenAI, model: str, voice: str, speed: float) -> None:
        self._client = client
        self._model = model
        self._voice = voice
        self._speed = speed

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        # HTTP chunks can split a sample in two: hold the odd byte back for the next chunk.
        pending = b""
        try:
            async with self._client.audio.speech.with_streaming_response.create(
                model=self._model,
                voice=self._voice,
                input=text,
                response_format="pcm",
                speed=self._speed,
            ) as response:
                async for chunk in response.iter_bytes():
                    data = pending + chunk
                    whole = len(data) - len(data) % SAMPLE_WIDTH_BYTES
                    pending = data[whole:]
                    if whole:
                        yield data[:whole]
        except openai.APIError as error:
            raise provider_error(error, base_url(self._client)) from error

    async def status(self) -> ModelStatus:
        return await model_status(self._client, self._model)
