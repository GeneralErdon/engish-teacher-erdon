"""Dependency wiring: the only place where ports are bound to adapters."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

import anthropic
import openai

from vt_api.adapters.chat_factory import SdkChatModelFactory
from vt_api.adapters.json_learner_profile import JsonLearnerProfileRepository
from vt_api.adapters.json_llm_config import JsonLlmConfigRepository
from vt_api.config import Settings
from vt_api.domain.llm import environment_config
from vt_api.services.learner import LearnerService
from vt_api.services.llm import LlmService
from vt_contracts.learner import LearnerProfile


@dataclass(frozen=True, slots=True)
class Container:
    llm: LlmService
    learner: LearnerService


@asynccontextmanager
async def build_container(settings: Settings) -> AsyncIterator[Container]:
    """The production wiring; closes every connection pool on exit."""
    async with AsyncExitStack() as stack:
        chat_models = SdkChatModelFactory(
            openai_http=openai.DefaultAsyncHttpxClient(),
            anthropic_http=anthropic.DefaultAsyncHttpxClient(),
        )
        stack.push_async_callback(chat_models.aclose)
        environment = environment_config(
            kind=settings.llm_provider,
            base_url=str(settings.llm_base_url),
            model=settings.llm_model,
            api_key=settings.llm_api_key,
        )
        yield Container(
            llm=LlmService(
                repository=JsonLlmConfigRepository(settings.settings_path),
                chat_models=chat_models,
                environment=environment,
            ),
            learner=LearnerService(
                repository=JsonLearnerProfileRepository(settings.learner_profile_path),
                environment=LearnerProfile(
                    level=settings.learner_level, explanations=settings.learner_explanations
                ),
                native_language=settings.learner_l1,
            ),
        )
