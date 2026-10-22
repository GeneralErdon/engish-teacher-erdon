"""`/v1/learner`: the learner's level and the language of correction explanations."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from vt_api.services.learner import LearnerService
from vt_contracts.learner import LearnerProfile, LearnerProfileView

router = APIRouter(prefix="/v1/learner", tags=["learner"])


def _learner_service(request: Request) -> LearnerService:
    service: LearnerService = request.app.state.container.learner
    return service


Learner = Annotated[LearnerService, Depends(_learner_service)]


@router.get("")
async def get_learner(learner: Learner) -> LearnerProfileView:
    return await learner.view()


@router.put("")
async def save_learner(body: LearnerProfile, learner: Learner) -> LearnerProfileView:
    return await learner.save(body)
