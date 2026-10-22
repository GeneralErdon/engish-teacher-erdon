"""Port for the learner profile saved from the UI."""

from typing import Protocol

from vt_contracts.learner import LearnerProfile


class LearnerProfileRepository(Protocol):
    async def load(self) -> LearnerProfile | None: ...

    async def save(self, profile: LearnerProfile) -> None: ...
