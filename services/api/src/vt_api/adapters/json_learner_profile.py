"""The learner profile saved from the UI, as a private JSON file."""

import logging
from pathlib import Path

from pydantic import ValidationError

from vt_api.adapters import private_json
from vt_contracts.learner import LearnerProfile

logger = logging.getLogger(__name__)


class JsonLearnerProfileRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    async def load(self) -> LearnerProfile | None:
        """`None` when nothing usable is saved: the environment's defaults apply."""
        raw = await private_json.read_or_none(self._path)
        if raw is None:
            return None
        try:
            return LearnerProfile.model_validate_json(raw)
        except ValidationError:
            logger.warning("Ignoring unreadable learner profile %s", self._path)
            return None

    async def save(self, profile: LearnerProfile) -> None:
        await private_json.write_private(self._path, profile.model_dump_json(indent=2))
