from collections.abc import AsyncIterator
from unittest.mock import create_autospec

import httpx2
import pytest
from sqlalchemy import text

from vt_api.adapters.sql.database import Database
from vt_api.config import Settings
from vt_api.container import Container
from vt_api.main import create_app
from vt_api.services.learner import LearnerService
from vt_api.services.llm import LlmService
from vt_api.services.speech import SpeechService
from vt_contracts.learner import LearnerProfileView


@pytest.fixture
async def client(learner_service: LearnerService) -> AsyncIterator[httpx2.AsyncClient]:
    container = Container(
        llm=create_autospec(LlmService, instance=True),
        learner=learner_service,
        speech=create_autospec(SpeechService, instance=True),
    )
    app = create_app(Settings(_env_file=None), container=container)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def test_defaults_come_from_the_environment(client: httpx2.AsyncClient) -> None:
    view = LearnerProfileView.model_validate_json((await client.get("/v1/learner")).content)

    assert view == LearnerProfileView(
        level="B1", explanations="native", native_language="es", source="environment"
    )


async def test_saving_the_profile(client: httpx2.AsyncClient) -> None:
    saved = await client.put("/v1/learner", json={"level": "C1", "explanations": "english"})

    assert saved.status_code == 200
    view = LearnerProfileView.model_validate_json((await client.get("/v1/learner")).content)
    assert (view.level, view.explanations, view.source) == ("C1", "english", "saved")


async def test_rejects_unknown_levels(client: httpx2.AsyncClient) -> None:
    response = await client.put("/v1/learner", json={"level": "D1", "explanations": "native"})

    assert response.status_code == 422


async def test_an_unreadable_profile_falls_back_to_the_environment(
    client: httpx2.AsyncClient, database: Database
) -> None:
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO learner_profile (id, level, explanations) VALUES (1, 'Z9', 'klingon')"
            )
        )

    view = LearnerProfileView.model_validate_json((await client.get("/v1/learner")).content)

    assert view.source == "environment"
