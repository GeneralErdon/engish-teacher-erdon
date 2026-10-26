"""Ports for speech: the learner's voice to text, and the tutor's text to voice."""

from collections.abc import AsyncIterator
from typing import Protocol

from vt_contracts.speech import ModelStatus, SpeechSettings


class SpeechToText(Protocol):
    async def transcribe(self, wav: bytes) -> str:
        """The English text spoken in `wav`. Raises `ProviderError`."""
        ...

    async def status(self) -> ModelStatus:
        """Whether the server answers and has the model; never raises."""
        ...


class TextToSpeech(Protocol):
    def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """`text` spoken as PCM16 little-endian mono at `OUTPUT_SAMPLE_RATE_HZ`, streamed as it
        is produced, in chunks of whole samples. Raises `ProviderError`."""
        ...

    async def status(self) -> ModelStatus:
        """Whether the server answers and has the model; never raises."""
        ...


class SpeechSettingsRepository(Protocol):
    async def load(self) -> SpeechSettings | None:
        """The saved settings, or `None` when nothing usable is saved."""
        ...

    async def save(self, settings: SpeechSettings) -> None: ...
