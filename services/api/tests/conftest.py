import os
from pathlib import Path

import pytest

from vt_api.adapters.json_learner_profile import JsonLearnerProfileRepository
from vt_api.services.learner import LearnerService
from vt_contracts.learner import LearnerProfile


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never see the developer's VT_* variables."""
    for name in os.environ:
        if name.startswith("VT_"):
            monkeypatch.delenv(name)


@pytest.fixture
def learner_service(tmp_path: Path) -> LearnerService:
    """The real service over a JSON file in a temporary directory; defaults B1, Spanish."""
    return LearnerService(
        repository=JsonLearnerProfileRepository(tmp_path / "learner.json"),
        environment=LearnerProfile(level="B1", explanations="native"),
        native_language="es",
    )
