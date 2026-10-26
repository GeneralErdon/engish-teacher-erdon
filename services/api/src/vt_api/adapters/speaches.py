"""Lists models and voices on a Speaches server, and unloads models from its memory."""

from typing import Any, Literal

import httpx2

from vt_api.adapters.provider_errors import connection_failed, from_status, timed_out
from vt_api.domain.llm import ProviderError
from vt_contracts.speech import Voice

_ACCENTS: dict[str, Literal["american", "british"]] = {"en-us": "american", "en-gb": "british"}
_GENDERS: dict[str, Literal["female", "male"]] = {"female": "female", "male": "male"}


class SpeachesServer:
    def __init__(self, http: httpx2.AsyncClient, base_url: str) -> None:
        self._http = http
        self._v1 = base_url.rstrip("/")
        self._root = self._v1.removesuffix("/v1")
        self._registry: list[Any] | None = None

    async def is_speaches(self) -> bool:
        """Asks the registry `voices()` reads, so one answer serves both and is kept; a failure
        is asked again on the next call."""
        try:
            await self._tts_registry()
        except ProviderError:
            return False
        return True

    async def installed(self) -> set[str]:
        data = await self._get_data(f"{self._root}/v1/models")
        try:
            return {model["id"] for model in data}
        except (TypeError, KeyError) as error:
            raise self._unexpected() from error

    async def voices(self, model_id: str) -> list[Voice]:
        for model in await self._tts_registry():
            if model["id"] == model_id:
                return [v for raw in model.get("voices", []) if (v := _english_voice(raw))]
        return []

    async def unload(self, model_id: str) -> None:
        url = f"{self._root}/api/ps/{model_id}"
        response = await self._send("DELETE", url)
        if response.status_code != 404:  # 404: the model was not loaded
            _raise_for_status(response)

    async def _tts_registry(self) -> list[Any]:
        """Speaches' text-to-speech models and their voices, fetched once it answers."""
        if self._registry is None:
            self._registry = await self._get_data(
                f"{self._root}/v1/registry", {"task": "text-to-speech"}
            )
        return self._registry

    async def _get_json(self, url: str, params: dict[str, str] | None = None) -> Any:
        response = await self._send("GET", url, params)
        _raise_for_status(response)
        try:
            return response.json()
        except ValueError as error:
            raise self._unexpected() from error

    async def _get_data(self, url: str, params: dict[str, str] | None = None) -> list[Any]:
        body = await self._get_json(url, params)
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise self._unexpected()
        data: list[Any] = body["data"]
        return data

    def _unexpected(self) -> ProviderError:
        return ProviderError("bad_request", f"{self._root} did not answer like a Speaches server.")

    async def _send(
        self, method: str, url: str, params: dict[str, str] | None = None
    ) -> httpx2.Response:
        try:
            return await self._http.request(method, url, params=params)
        except httpx2.TimeoutException as error:
            raise timed_out(self._root) from error
        except httpx2.HTTPError as error:
            raise connection_failed(self._root) from error


def _raise_for_status(response: httpx2.Response) -> None:
    if response.is_error:
        raise from_status(response.status_code, response.text)


def _english_voice(raw: dict[str, Any]) -> Voice | None:
    language = raw.get("language")
    if language is not None and not language.lower().startswith("en"):
        return None
    return Voice(
        id=raw["id"],
        name=raw.get("name", raw["id"]),
        accent=_ACCENTS.get((language or "").lower()),
        gender=_GENDERS.get(raw.get("gender") or ""),
    )
