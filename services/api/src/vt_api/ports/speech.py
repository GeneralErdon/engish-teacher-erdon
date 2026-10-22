"""Port for speech-to-text."""

from typing import Protocol

from vt_contracts.speech import SpeechStatus


class SpeechToText(Protocol):
    async def transcribe(self, wav: bytes) -> str:
        """The English text spoken in `wav`. Raises `ProviderError`."""
        ...

    async def status(self) -> SpeechStatus:
        """Whether the server answers and has the model; never raises."""
        ...
