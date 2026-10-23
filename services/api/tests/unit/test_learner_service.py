from vt_api.services.learner import LearnerService
from vt_contracts.learner import LearnerProfile


async def test_profile_is_the_saved_one_or_the_default(learner_service: LearnerService) -> None:
    assert await learner_service.profile() == LearnerProfile(level="B1", explanations="native")

    await learner_service.save(LearnerProfile(level="A2", explanations="english"))

    assert await learner_service.profile() == LearnerProfile(level="A2", explanations="english")
    assert learner_service.native_language == "es"
