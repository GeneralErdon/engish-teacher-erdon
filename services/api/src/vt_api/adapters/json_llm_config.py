"""Provider settings saved from the UI, as a JSON file readable only by its owner (mode 0600)."""

import logging
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError, model_validator

from vt_api.adapters import private_json
from vt_api.domain.llm import LlmConfig, ProviderConfig
from vt_contracts.llm import ProviderKind

logger = logging.getLogger(__name__)


class _StoredProvider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    model: str
    api_key: str


class _StoredSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    active: ProviderKind
    providers: dict[ProviderKind, _StoredProvider]

    @model_validator(mode="after")
    def _active_is_configured(self) -> Self:
        if self.active not in self.providers:
            msg = f"active provider {self.active!r} has no settings"
            raise ValueError(msg)
        return self


class JsonLlmConfigRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    async def load(self) -> LlmConfig | None:
        """`None` when nothing is saved, or when the file is unreadable: a broken file must not
        stop the api, the environment's settings apply and the next save rewrites it."""
        raw = await private_json.read_or_none(self._path)
        if raw is None:
            return None
        try:
            stored = _StoredSettings.model_validate_json(raw)
        except ValidationError:
            logger.warning("Ignoring unreadable LLM settings file %s", self._path)
            return None
        providers = {
            kind: ProviderConfig(kind, p.base_url, p.model, SecretStr(p.api_key))
            for kind, p in stored.providers.items()
        }
        return LlmConfig(active=stored.active, providers=providers, source="saved")

    async def save(self, config: LlmConfig) -> None:
        stored = _StoredSettings(
            active=config.active,
            providers={
                kind: _StoredProvider(
                    base_url=p.base_url, model=p.model, api_key=p.api_key.get_secret_value()
                )
                for kind, p in config.providers.items()
            },
        )
        await private_json.write_private(self._path, stored.model_dump_json(indent=2))

    async def clear(self) -> None:
        await private_json.delete(self._path)
