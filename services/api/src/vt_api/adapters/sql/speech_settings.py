"""The speech settings saved from the UI, in the encrypted database."""

import logging

import anyio
from pydantic import ValidationError
from sqlalchemy.orm import Session

from vt_api.adapters.sql.database import Database
from vt_api.adapters.sql.tables import SpeechSettingsRow
from vt_contracts.speech import SpeechSettings

logger = logging.getLogger(__name__)


class SqlSpeechSettingsRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def load(self) -> SpeechSettings | None:
        return await anyio.to_thread.run_sync(self._load)

    async def save(self, settings: SpeechSettings) -> None:
        await anyio.to_thread.run_sync(self._save, settings)

    def _load(self) -> SpeechSettings | None:
        """`None` when nothing usable is saved: the environment's defaults apply."""
        with Session(self._db.engine) as session:
            row = session.get(SpeechSettingsRow, 1)
        if row is None:
            return None
        try:
            return SpeechSettings.model_validate(
                {
                    "stt_model": row.stt_model,
                    "stt_engine": row.stt_engine,
                    "stt_gpu_model": row.stt_gpu_model,
                    "tts_model": row.tts_model,
                    "tts_voice": row.tts_voice,
                    "tts_speed": row.tts_speed,
                    "max_turn_s": row.max_turn_s,
                }
            )
        except ValidationError:
            logger.warning("Ignoring unreadable saved speech settings")
            return None

    def _save(self, settings: SpeechSettings) -> None:
        with Session(self._db.engine) as session, session.begin():
            session.merge(SpeechSettingsRow(id=1, **settings.model_dump()))
