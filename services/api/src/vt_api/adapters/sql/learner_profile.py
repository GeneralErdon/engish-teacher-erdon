"""The learner profile saved from the UI, in the encrypted database."""

import logging

import anyio
from pydantic import ValidationError
from sqlalchemy.orm import Session

from vt_api.adapters.sql.database import Database
from vt_api.adapters.sql.tables import LearnerProfileRow
from vt_contracts.learner import LearnerProfile

logger = logging.getLogger(__name__)


class SqlLearnerProfileRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def load(self) -> LearnerProfile | None:
        return await anyio.to_thread.run_sync(self._load)

    async def save(self, profile: LearnerProfile) -> None:
        await anyio.to_thread.run_sync(self._save, profile)

    def _load(self) -> LearnerProfile | None:
        """`None` when nothing usable is saved: the environment's defaults apply."""
        with Session(self._db.engine) as session:
            row = session.get(LearnerProfileRow, 1)
        if row is None:
            return None
        try:
            return LearnerProfile.model_validate(
                {"level": row.level, "explanations": row.explanations}
            )
        except ValidationError:
            logger.warning("Ignoring an unreadable saved learner profile")
            return None

    def _save(self, profile: LearnerProfile) -> None:
        with Session(self._db.engine) as session, session.begin():
            session.merge(
                LearnerProfileRow(id=1, level=profile.level, explanations=profile.explanations)
            )
