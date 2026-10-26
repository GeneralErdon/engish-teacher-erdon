import os
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest

from vt_api.adapters.secret_key import MasterKey
from vt_api.adapters.sql.database import Database, open_database
from vt_api.adapters.sql.learner_profile import SqlLearnerProfileRepository
from vt_api.services.learner import LearnerService
from vt_contracts.learner import LearnerProfile
from vt_contracts.speech import SpeechSettings

# Never touch the developer's real keyring: with this backend, there is none.
os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never see the developer's VT_* variables."""
    for name in os.environ:
        if name.startswith("VT_"):
            monkeypatch.delenv(name)


@pytest.fixture
def master_key() -> MasterKey:
    return MasterKey(secrets.token_bytes(32), "environment", "VT_SECRET_KEY")


@pytest.fixture
def database(tmp_path: Path, master_key: MasterKey) -> Iterator[Database]:
    """A fresh encrypted database, migrated, in a temporary directory."""
    database = open_database(f"sqlite:///{tmp_path}/voice-tutor.db", master_key)
    yield database
    database.close()


@pytest.fixture
def learner_service(database: Database) -> LearnerService:
    """The real service over the encrypted database; defaults B1, Spanish."""
    return LearnerService(
        repository=SqlLearnerProfileRepository(database),
        environment=LearnerProfile(level="B1", explanations="native"),
        native_language="es",
    )


@pytest.fixture
def speech_defaults() -> SpeechSettings:
    """The speech settings when nothing is saved: the defaults of `VT_STT_MODEL`, `VT_TTS_*` and
    `VT_MAX_TURN_S`."""
    return SpeechSettings(
        stt_model="Systran/faster-distil-whisper-small.en",
        tts_model="speaches-ai/Kokoro-82M-v1.0-ONNX",
        tts_voice="af_heart",
        tts_speed=0.95,
        max_turn_s=120,
    )
