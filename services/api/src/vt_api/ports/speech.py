"""Ports for speech: the learner's voice to text, and the tutor's text to voice."""

from collections.abc import AsyncIterator
from typing import Protocol

from vt_contracts.speech import DownloadProgress, ModelStatus, SpeechSettings, Voice


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


class ModelFiles(Protocol):
    """The Hugging Face cache folder that the speech server reads its models from."""

    def progress(self) -> tuple[str, DownloadProgress] | None:
        """The model being downloaded and its bytes so far, or `None`."""
        ...

    async def download(self, model_id: str) -> None:
        """Download a model that is not installed; returns once its files are complete.

        Raises `SpeechSettingsError`: 507 before starting when the disk is too small, 502 when
        the download fails. Raises `asyncio.CancelledError` when cancelled. A failed or
        cancelled download leaves no files behind.
        """
        ...

    async def cancel(self) -> None:
        """Stop the running download, if any, and remove its files."""
        ...

    async def delete(self, model_id: str) -> None:
        """Remove the model's files; fine if there are none. Raises `SpeechSettingsError` (500)
        when they cannot be removed."""
        ...

    def cleanup(self) -> None:
        """Remove the half-written models an api killed mid-download left behind, once nothing
        has written to them for a while, so the server never lists them."""
        ...
