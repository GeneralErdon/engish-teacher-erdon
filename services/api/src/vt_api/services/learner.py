"""The learner's level and how corrections are explained: saved from the UI, defaults from
`VT_LEARNER_*`."""

from vt_api.ports.learner import LearnerProfileRepository
from vt_contracts.learner import LearnerProfile, LearnerProfileView


class LearnerService:
    def __init__(
        self,
        *,
        repository: LearnerProfileRepository,
        environment: LearnerProfile,
        native_language: str,
    ) -> None:
        self._repository = repository
        self._environment = environment
        self._native_language = native_language

    @property
    def native_language(self) -> str:
        return self._native_language

    async def profile(self) -> LearnerProfile:
        return await self._repository.load() or self._environment

    async def view(self) -> LearnerProfileView:
        saved = await self._repository.load()
        return self._view(saved or self._environment, saved is not None)

    async def save(self, profile: LearnerProfile) -> LearnerProfileView:
        await self._repository.save(profile)
        return self._view(profile, saved=True)

    def _view(self, profile: LearnerProfile, saved: bool) -> LearnerProfileView:
        return LearnerProfileView(
            **profile.model_dump(),
            native_language=self._native_language,
            source="saved" if saved else "environment",
        )
