"""Provider settings saved from the UI, in the encrypted database. Each API key is also sealed
in its own column (`SecretBox`), bound to its provider and URL."""

import logging
from typing import TypeIs

import anyio
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from vt_api.adapters.secret_box import SecretBoxError
from vt_api.adapters.sql.database import Database
from vt_api.adapters.sql.tables import LlmProviderRow, LlmSettingsRow
from vt_api.domain.llm import PROVIDERS, LlmConfig, ProviderConfig
from vt_contracts.llm import ProviderKind

logger = logging.getLogger(__name__)


def _is_kind(value: str) -> TypeIs[ProviderKind]:
    return value in PROVIDERS


def _key_context(kind: str, base_url: str) -> str:
    """What a sealed key is bound to: moved to another provider or URL, it does not open."""
    return f"llm_providers.api_key|{kind}|{base_url}"


class SqlLlmConfigRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def load(self) -> LlmConfig | None:
        return await anyio.to_thread.run_sync(self._load)

    async def save(self, config: LlmConfig) -> None:
        await anyio.to_thread.run_sync(self._save, config)

    async def clear(self) -> None:
        await anyio.to_thread.run_sync(self._clear)

    def _load(self) -> LlmConfig | None:
        """`None` when nothing usable is saved: the environment's settings apply."""
        with Session(self._db.engine) as session:
            settings = session.get(LlmSettingsRow, 1)
            rows = session.scalars(select(LlmProviderRow)).all()
        if settings is None:
            return None
        providers: dict[ProviderKind, ProviderConfig] = {}
        for row in rows:
            if _is_kind(row.kind):
                providers[row.kind] = ProviderConfig(
                    row.kind, row.base_url, row.model, self._api_key(row)
                )
            else:
                logger.warning("Ignoring saved settings for unknown provider %r", row.kind)
        if not _is_kind(settings.active) or settings.active not in providers:
            logger.warning("Ignoring saved LLM settings: the active provider has none")
            return None
        return LlmConfig(active=settings.active, providers=providers, source="saved")

    def _api_key(self, row: LlmProviderRow) -> SecretStr:
        if row.api_key is None:
            return SecretStr("")
        try:
            return SecretStr(
                self._db.secrets.open(row.api_key, _key_context(row.kind, row.base_url))
            )
        except SecretBoxError:
            logger.error("The saved API key for %s cannot be decrypted: enter it again", row.kind)
            return SecretStr("")

    def _save(self, config: LlmConfig) -> None:
        with Session(self._db.engine) as session, session.begin():
            session.execute(delete(LlmProviderRow))
            session.merge(LlmSettingsRow(id=1, active=config.active))
            session.add_all(
                LlmProviderRow(
                    kind=kind,
                    base_url=provider.base_url,
                    model=provider.model,
                    api_key=self._seal(provider),
                )
                for kind, provider in config.providers.items()
            )

    def _seal(self, provider: ProviderConfig) -> bytes | None:
        key = provider.api_key.get_secret_value()
        if not key:
            return None
        return self._db.secrets.seal(key, _key_context(provider.kind, provider.base_url))

    def _clear(self) -> None:
        with Session(self._db.engine) as session, session.begin():
            session.execute(delete(LlmProviderRow))
            session.execute(delete(LlmSettingsRow))
