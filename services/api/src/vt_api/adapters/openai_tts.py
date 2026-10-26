"""Text-to-speech over the OpenAI-compatible `/audio/speech` API (official `openai` SDK):
Kokoro in Speaches locally, Kokoro-FastAPI, or any compatible server that streams raw PCM at
Kokoro's 24 kHz."""

from collections.abc import AsyncIterator

import openai

from vt_api.adapters.openai_chat import provider_error
from vt_api.adapters.openai_models import base_url, model_status
from vt_api.domain.speech import VoiceChoice
from vt_contracts.audio import SAMPLE_WIDTH_BYTES
from vt_contracts.speech import ModelStatus


class OpenAITextToSpeech:
    def __init__(self, client: openai.AsyncOpenAI) -> None:
        self._client = client

    async def synthesize(self, text: str, voice: VoiceChoice) -> AsyncIterator[bytes]:
        # HTTP chunks can split a sample in two: hold the odd byte back for the next chunk.
        pending = b""
        # Piper makes 22.05 kHz audio: ask Speaches to resample it to what the player expects.
        extra_body = {"sample_rate": voice.sample_rate_hz} if voice.sample_rate_hz else None
        try:
            async with self._client.audio.speech.with_streaming_response.create(
                model=voice.model,
                voice=voice.voice,
                input=text,
                response_format="pcm",
                speed=voice.speed,
                extra_body=extra_body,
            ) as response:
                async for chunk in response.iter_bytes():
                    data = pending + chunk
                    whole = len(data) - len(data) % SAMPLE_WIDTH_BYTES
                    pending = data[whole:]
                    if whole:
                        yield data[:whole]
        except openai.APIError as error:
            raise provider_error(error, base_url(self._client)) from error

    async def status(self, model: str) -> ModelStatus:
        return await model_status(self._client, model)
