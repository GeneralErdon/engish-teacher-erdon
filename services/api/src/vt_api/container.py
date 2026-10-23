"""Dependency wiring: the only place where ports are bound to adapters."""

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

import anthropic
import anyio
import openai
from pydantic import HttpUrl

from vt_api.adapters.chat_factory import SdkChatModelFactory
from vt_api.adapters.openai_stt import OpenAISpeechToText
from vt_api.adapters.openai_tts import OpenAITextToSpeech
from vt_api.adapters.secret_key import MasterKey, load_master_key, usable_keyring
from vt_api.adapters.sql.database import Database, open_database
from vt_api.adapters.sql.learner_profile import SqlLearnerProfileRepository
from vt_api.adapters.sql.llm_config import SqlLlmConfigRepository
from vt_api.config import Settings
from vt_api.domain.llm import environment_config
from vt_api.ports.speech import SpeechToText, TextToSpeech
from vt_api.services.learner import LearnerService
from vt_api.services.llm import LlmService
from vt_contracts.learner import LearnerProfile

logger = logging.getLogger(__name__)

STT_TIMEOUT_S = 60.0
"""A long turn on a slow CPU can take a while to transcribe."""
TTS_TIMEOUT_S = 30.0
"""Per read: the first sentence loads the voice model if the server unloaded it."""


@dataclass(frozen=True, slots=True)
class Container:
    llm: LlmService
    learner: LearnerService
    stt: SpeechToText
    tts: TextToSpeech


def _open_database(settings: Settings) -> Database:
    """The master key, then the encrypted database. Blocking: files, D-Bus, SQLCipher."""
    secret = settings.secret_key.get_secret_value() if settings.secret_key else None
    master: MasterKey = load_master_key(
        environment=secret,
        key_file=settings.secret_key_file,
        keyring=usable_keyring() if settings.keyring else None,
    )
    database = open_database(settings.database_url, master)
    logger.info("Settings database ready; its key comes from %s", master.where)
    return database


@asynccontextmanager
async def build_container(settings: Settings) -> AsyncIterator[Container]:
    """The production wiring; closes every connection pool on exit. Fails at startup if the
    database cannot be opened."""
    async with AsyncExitStack() as stack:
        database = await anyio.to_thread.run_sync(_open_database, settings)
        stack.callback(database.close)
        chat_models = SdkChatModelFactory(
            openai_http=openai.DefaultAsyncHttpxClient(),
            anthropic_http=anthropic.DefaultAsyncHttpxClient(),
        )
        stack.push_async_callback(chat_models.aclose)
        speech_http = openai.DefaultAsyncHttpxClient()
        stack.push_async_callback(speech_http.aclose)

        def speech_client(base_url: HttpUrl, timeout: float) -> openai.AsyncOpenAI:
            return openai.AsyncOpenAI(
                # Local Speaches needs no key; never let the SDK fall back to OPENAI_API_KEY.
                api_key="none",
                base_url=str(base_url),
                http_client=speech_http,
                timeout=timeout,
                max_retries=0,
            )

        stt = OpenAISpeechToText(
            speech_client(settings.stt_base_url, STT_TIMEOUT_S), settings.stt_model
        )
        tts = OpenAITextToSpeech(
            speech_client(settings.tts_base_url, TTS_TIMEOUT_S),
            model=settings.tts_model,
            voice=settings.tts_voice,
            speed=settings.tts_speed,
        )
        environment = environment_config(
            kind=settings.llm_provider,
            base_url=str(settings.llm_base_url),
            model=settings.llm_model,
            api_key=settings.llm_api_key,
        )
        yield Container(
            llm=LlmService(
                repository=SqlLlmConfigRepository(database),
                chat_models=chat_models,
                environment=environment,
            ),
            learner=LearnerService(
                repository=SqlLearnerProfileRepository(database),
                environment=LearnerProfile(
                    level=settings.learner_level, explanations=settings.learner_explanations
                ),
                native_language=settings.learner_l1,
            ),
            stt=stt,
            tts=tts,
        )
