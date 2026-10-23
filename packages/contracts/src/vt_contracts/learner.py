"""The learner's profile: `GET`/`PUT /v1/learner`."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

type CefrLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]

type ExplanationLanguage = Literal["english", "native"]
"""Language of correction explanations: English, or the learner's native language."""


class LearnerProfile(BaseModel):
    """What the learner can change from the UI. Body of `PUT /v1/learner`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level: CefrLevel
    explanations: ExplanationLanguage


class LearnerProfileView(LearnerProfile):
    """Body of `GET`/`PUT /v1/learner`."""

    native_language: str
    """ISO 639 code (`VT_LEARNER_L1`), e.g. `es`."""
    source: Literal["environment", "saved"]
