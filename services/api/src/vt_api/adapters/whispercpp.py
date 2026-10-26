"""Speech-to-text on a whisper.cpp server (`whisper-server --request-path /v1
--inference-path /audio/transcriptions`), which holds one model in GPU memory at a time.

`POST /load` swaps the model; loads and inference share one mutex on the server, so the adapter
serialises them too. A model file that exists but does not load makes the server process exit,
which drops the connection, so a failed load always forgets the loaded model. Written against
`httpx2` rather than the openai SDK: only the transport tells a refused connection (the server
is not running) from a read timeout (it is slow).
"""

import asyncio
from typing import Any

import httpx2

from vt_api.adapters.openai_stt import LANGUAGE
from vt_api.adapters.provider_errors import connection_failed, from_status, timed_out
from vt_api.domain.llm import ProviderError
from vt_api.domain.speech import EngineUnreachable
from vt_contracts.speech import ModelStatus

CONNECT_TIMEOUT_S = 3.0
HEALTH_TIMEOUT_S = 3.0
LOAD_TIMEOUT_S = 120.0


class WhisperCppSpeechToText:
    def __init__(self, http: httpx2.AsyncClient, base_url: str, models_root: str) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._models_root = models_root.rstrip("/")
        self._loaded: str | None = None
        self._lock = asyncio.Lock()

    async def transcribe(self, wav: bytes, model: str, timeout_s: float) -> str:
        async with self._lock:
            await self._ensure_loaded(model)
            response = await self._send(
                "/audio/transcriptions",
                timeout_s,
                files={"file": ("speech.wav", wav, "audio/wav")},
                data={"response_format": "json", "language": LANGUAGE},
            )
        try:
            return str(response.json()["text"]).strip()
        except (ValueError, KeyError, TypeError) as error:
            raise ProviderError(
                "bad_request", f"{self._base_url} did not answer like whisper.cpp."
            ) from error

    async def running(self) -> bool:
        """503 means it is loading a model, which still means it is running."""
        try:
            response = await self._http.get(
                f"{self._base_url}/health", timeout=_timeout(HEALTH_TIMEOUT_S)
            )
        except httpx2.HTTPError:
            return False
        return response.status_code in (200, 503)

    async def load(self, model: str) -> None:
        async with self._lock:
            await self._ensure_loaded(model)

    async def status(self, model: str) -> ModelStatus:
        """Never raises. whisper.cpp cannot say which model it holds, so `model_ready` only
        means it is not busy loading one."""
        status = ModelStatus(
            base_url=self._base_url, model=model, reachable=False, model_ready=False
        )
        try:
            response = await self._http.get(
                f"{self._base_url}/health", timeout=_timeout(HEALTH_TIMEOUT_S)
            )
        except httpx2.ConnectError, httpx2.ConnectTimeout:
            return status.model_copy(update={"detail": EngineUnreachable(self._base_url).message})
        except httpx2.TimeoutException:
            return status.model_copy(update={"detail": timed_out(self._base_url).message})
        except httpx2.HTTPError:
            return status.model_copy(update={"detail": connection_failed(self._base_url).message})
        if response.status_code == 200:
            return status.model_copy(update={"reachable": True, "model_ready": True})
        if response.status_code == 503:
            return status.model_copy(
                update={"reachable": True, "detail": "whisper.cpp is loading a model."}
            )
        return status.model_copy(
            update={"detail": from_status(response.status_code, response.text).message}
        )

    async def _ensure_loaded(self, model: str) -> None:
        """Called with the lock held."""
        if model == self._loaded:
            return
        self._loaded = None
        await self._send(
            "/load",
            LOAD_TIMEOUT_S,
            files={"model": (None, f"{self._models_root}/{model}")},
        )
        self._loaded = model

    async def _send(self, path: str, timeout_s: float, **content: Any) -> httpx2.Response:
        """POSTs to the server; raises `ProviderError` (`EngineUnreachable` when it refuses the
        connection) and forgets the loaded model on any failure."""
        try:
            response = await self._http.post(
                f"{self._base_url}{path}", timeout=_timeout(timeout_s), **content
            )
        except (httpx2.ConnectError, httpx2.ConnectTimeout) as error:
            self._loaded = None
            raise EngineUnreachable(self._base_url) from error
        except httpx2.TimeoutException as error:
            self._loaded = None
            raise timed_out(self._base_url) from error
        except httpx2.HTTPError as error:
            self._loaded = None
            raise connection_failed(self._base_url) from error
        if response.is_error:
            self._loaded = None
            raise from_status(response.status_code, _error_text(response))
        return response


def _timeout(seconds: float) -> httpx2.Timeout:
    return httpx2.Timeout(seconds, connect=CONNECT_TIMEOUT_S)


def _error_text(response: httpx2.Response) -> str:
    """The server's `{"error": "..."}` text, or the raw body (a 500 may be plain text)."""
    try:
        error = response.json()["error"]
    except ValueError, KeyError, TypeError:
        return response.text
    return str(error)
