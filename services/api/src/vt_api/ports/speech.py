"""Ports for speech: the learner's voice to text, and the tutor's text to voice."""

from collections.abc import AsyncIterator
from typing import Protocol

from vt_contracts.speech import ModelStatus, SpeechSettings, Voice


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


class SpeechModelServer(Protocol):
    """The server that holds the speech models (Speaches)."""

    async def is_speaches(self) -> bool:
        """Whether the server is Speaches, which can list and unload models; never raises."""
        ...

    async def installed(self) -> set[str]:
        """The ids of the models downloaded on the server. Raises `ProviderError`."""
        ...

    async def voices(self, model_id: str) -> list[Voice]:
        """The English voices of `model_id`; empty for an unknown model. Raises `ProviderError`."""
        ...

    async def unload(self, model_id: str) -> None:
        """Free `model_id` from memory; fine if it was not loaded. Raises `ProviderError`."""
        ...
