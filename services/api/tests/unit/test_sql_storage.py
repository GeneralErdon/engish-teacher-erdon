"""The encrypted database and its repositories, on real SQLCipher files in a temp directory."""

import logging
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from pydantic import SecretStr
from sqlalchemy import text

from vt_api.adapters.secret_key import MasterKey
from vt_api.adapters.sql.database import (
    Database,
    DatabaseKeyError,
    migrate,
    open_database,
    sqlite_path,
)
from vt_api.adapters.sql.learner_profile import SqlLearnerProfileRepository
from vt_api.adapters.sql.llm_config import SqlLlmConfigRepository
from vt_api.adapters.sql.speech_settings import SqlSpeechSettingsRepository
from vt_api.adapters.sql.tables import Base
from vt_api.domain.llm import LlmConfig, ProviderConfig
from vt_contracts.learner import LearnerProfile
from vt_contracts.speech import SpeechSettings

# Built from parts so secret scanners do not flag a fake key.
FAKE_KEY = "sk-" + "fake" * 3 + "3456"


def _config(api_key: str = FAKE_KEY) -> LlmConfig:
    providers = {
        "ollama_cloud": ProviderConfig(
            "ollama_cloud", "https://ollama.com", "gpt-oss:120b", SecretStr(api_key)
        ),
        "ollama": ProviderConfig("ollama", "http://localhost:11434", "gemma3", SecretStr("")),
    }
    return LlmConfig(active="ollama_cloud", providers=providers, source="saved")  # type: ignore[arg-type]


# ---------------------------------------------------------------- the file


def test_the_file_is_encrypted_and_private(database: Database, tmp_path: Path) -> None:
    path = tmp_path / "voice-tutor.db"

    assert path.stat().st_mode & 0o777 == 0o600
    assert not path.read_bytes().startswith(b"SQLite format 3")
    plain = sqlite3.connect(path)  # the standard sqlite3, without SQLCipher
    with closing(plain), pytest.raises(sqlite3.DatabaseError, match="not a database"):
        plain.execute("SELECT * FROM llm_settings").fetchall()


def test_an_older_readable_file_is_made_private(tmp_path: Path, master_key: MasterKey) -> None:
    path = tmp_path / "voice-tutor.db"
    path.touch(mode=0o644)

    open_database(f"sqlite:///{path}", master_key).close()

    assert path.stat().st_mode & 0o777 == 0o600


def test_another_key_does_not_open_it(database: Database, tmp_path: Path) -> None:
    other = MasterKey(secrets.token_bytes(32), "keyring", "keyring: service voice-tutor")

    with pytest.raises(DatabaseKeyError, match="key from keyring: service voice-tutor"):
        open_database(f"sqlite:///{tmp_path}/voice-tutor.db", other)


@pytest.mark.parametrize(
    "url", ["postgresql://db/voice", "sqlite://", "sqlite:///:memory:", "mysql:///x"]
)
def test_only_sqlite_files_for_now(url: str) -> None:
    with pytest.raises(ValueError, match="must point to a SQLite file"):
        sqlite_path(url)


def test_the_migrations_match_the_tables(database: Database) -> None:
    with database.engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert differences == []


def test_migrations_go_down_and_up_again(database: Database) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", "vt_api.adapters.sql:migrations")
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
        tables = connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        assert [name for (name,) in tables] == ["alembic_version"]

    migrate(database.engine)  # idempotent once at head
    migrate(database.engine)


# ---------------------------------------------------------------- LLM settings


async def test_nothing_saved_yet(database: Database) -> None:
    assert await SqlLlmConfigRepository(database).load() is None


async def test_settings_round_trip(database: Database) -> None:
    repository = SqlLlmConfigRepository(database)

    await repository.save(_config())
    loaded = await repository.load()

    assert loaded is not None
    assert (loaded.active, loaded.source) == ("ollama_cloud", "saved")
    cloud = loaded.providers["ollama_cloud"]
    assert (cloud.base_url, cloud.model, cloud.api_key.get_secret_value()) == (
        "https://ollama.com",
        "gpt-oss:120b",
        FAKE_KEY,
    )
    assert loaded.providers["ollama"].api_key.get_secret_value() == ""


async def test_keys_are_sealed_inside_the_encrypted_file(database: Database) -> None:
    await SqlLlmConfigRepository(database).save(_config())

    with database.engine.connect() as connection:
        result = connection.execute(text("SELECT kind, api_key FROM llm_providers"))
        rows: dict[str, bytes | None] = {row.kind: row.api_key for row in result}

    sealed = rows["ollama_cloud"]
    assert rows["ollama"] is None
    assert sealed is not None
    assert FAKE_KEY.encode() not in sealed


async def test_a_key_moved_to_another_url_does_not_open(
    database: Database, caplog: pytest.LogCaptureFixture
) -> None:
    repository = SqlLlmConfigRepository(database)
    await repository.save(_config())
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE llm_providers SET base_url = 'https://evil.example' "
                "WHERE kind = 'ollama_cloud'"
            )
        )

    with caplog.at_level(logging.ERROR):
        loaded = await repository.load()

    assert loaded is not None
    assert loaded.providers["ollama_cloud"].api_key.get_secret_value() == ""
    assert "cannot be decrypted" in caplog.text
    assert FAKE_KEY not in caplog.text


async def test_saving_replaces_everything(database: Database) -> None:
    repository = SqlLlmConfigRepository(database)
    await repository.save(_config())
    only_local = LlmConfig(
        active="ollama",
        providers={
            "ollama": ProviderConfig("ollama", "http://localhost:11434", "qwen3", SecretStr(""))
        },
        source="saved",
    )

    await repository.save(only_local)
    loaded = await repository.load()

    assert loaded is not None
    assert list(loaded.providers) == ["ollama"]
    assert loaded.providers["ollama"].model == "qwen3"


async def test_clear(database: Database) -> None:
    repository = SqlLlmConfigRepository(database)
    await repository.save(_config())

    await repository.clear()

    assert await repository.load() is None


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE llm_settings SET active = 'ollama'",  # configured, but deleted below
        "UPDATE llm_settings SET active = 'mistral'",  # a provider this version does not know
    ],
)
async def test_unusable_settings_fall_back_to_the_environment(
    database: Database, statement: str
) -> None:
    repository = SqlLlmConfigRepository(database)
    await repository.save(_config())
    with database.engine.begin() as connection:
        connection.execute(text(statement))
        connection.execute(text("DELETE FROM llm_providers WHERE kind = 'ollama'"))

    assert await repository.load() is None


async def test_unknown_providers_are_skipped(database: Database) -> None:
    repository = SqlLlmConfigRepository(database)
    await repository.save(_config())
    with database.engine.begin() as connection:
        connection.execute(
            text("INSERT INTO llm_providers (kind, base_url, model) VALUES ('mistral', 'u', 'm')")
        )

    loaded = await repository.load()

    assert loaded is not None
    assert sorted(loaded.providers) == ["ollama", "ollama_cloud"]


# ---------------------------------------------------------------- learner profile


async def test_learner_profile_round_trip(database: Database) -> None:
    repository = SqlLearnerProfileRepository(database)
    assert await repository.load() is None

    await repository.save(LearnerProfile(level="A2", explanations="english"))
    await repository.save(LearnerProfile(level="C1", explanations="native"))

    assert await repository.load() == LearnerProfile(level="C1", explanations="native")


# ---------------------------------------------------------------- speech settings


def _speech_settings(**changes: object) -> SpeechSettings:
    values: dict[str, object] = {
        "stt_model": "Systran/faster-distil-whisper-small.en",
        "tts_model": "speaches-ai/Kokoro-82M-v1.0-ONNX",
        "tts_voice": "af_heart",
        "tts_speed": 0.95,
        "max_turn_s": 120,
    }
    return SpeechSettings.model_validate(values | changes)


async def test_speech_settings_round_trip(database: Database) -> None:
    repository = SqlSpeechSettingsRepository(database)
    assert await repository.load() is None

    await repository.save(_speech_settings())
    await repository.save(_speech_settings(tts_voice="am_adam", tts_speed=1.1, max_turn_s=300))

    assert await repository.load() == _speech_settings(
        tts_voice="am_adam", tts_speed=1.1, max_turn_s=300
    )


async def test_unreadable_speech_settings_fall_back(
    database: Database, caplog: pytest.LogCaptureFixture
) -> None:
    repository = SqlSpeechSettingsRepository(database)
    await repository.save(_speech_settings())
    with database.engine.begin() as connection:
        connection.execute(text("UPDATE speech_settings SET max_turn_s = 5"))

    with caplog.at_level(logging.WARNING):
        assert await repository.load() is None

    assert "unreadable saved speech settings" in caplog.text
