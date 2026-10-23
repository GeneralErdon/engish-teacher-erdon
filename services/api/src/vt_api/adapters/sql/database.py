"""The encrypted database: SQLCipher (AES-256 on every page, with the bundled OpenSSL), a file
only its owner can read, and the schema migrated at startup.

Blocking calls: the repositories run them in worker threads. A settings store sees a few
queries per minute at most, so a thread per query costs nothing and keeps one synchronous code
path for SQLite today and Postgres later.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, create_engine, event, make_url
from sqlalchemy.exc import DatabaseError as SqlDatabaseError

from vt_api.adapters.secret_box import SecretBox, derive_key
from vt_api.adapters.secret_key import MasterKey

MIGRATIONS = "vt_api.adapters.sql:migrations"


class DatabaseKeyError(Exception):
    """The database exists but this key does not open it; the message says what to do."""


@dataclass(frozen=True, slots=True)
class Database:
    engine: Engine
    secrets: SecretBox
    """Seals secret columns (API keys) on top of the file encryption."""

    def close(self) -> None:
        self.engine.dispose()


def sqlite_path(url: str) -> Path:
    """The file behind a `sqlite:///` URL. Only SQLite is supported for now."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or parsed.database in (None, "", ":memory:"):
        msg = (
            "VT_DATABASE_URL must point to a SQLite file, e.g. sqlite:///data/voice-tutor.db "
            f"(got {parsed.render_as_string()})"
        )
        raise ValueError(msg)
    return Path(parsed.database)


def open_database(url: str, master: MasterKey) -> Database:
    """Open (or create) the database and bring its schema up to date. Blocking."""
    path = sqlite_path(url)
    _create_private_file(path)
    # A raw 256-bit key (`x'...'`): SQLCipher skips its passphrase derivation.
    raw_key = derive_key(master.value, "sqlcipher").hex()
    engine = create_engine(
        URL.create("sqlite+pysqlcipher", password=f"x'{raw_key}'", database=str(path))
    )
    event.listen(engine, "connect", _configure_connection)
    try:
        migrate(engine)
    except SqlDatabaseError as error:
        engine.dispose()
        msg = (
            f"Cannot open the database {path} with the key from {master.where}: it was "
            "encrypted with another key, or it is damaged. Use the original key (VT_SECRET_KEY "
            "or VT_SECRET_KEY_FILE), or move the file away to start with empty settings."
        )
        raise DatabaseKeyError(msg) from error
    return Database(engine, SecretBox(derive_key(master.value, "columns")))


def migrate(engine: Engine) -> None:
    config = Config()
    config.set_main_option("script_location", MIGRATIONS)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def _create_private_file(path: Path) -> None:
    """Mode 0600 from the start: SQLite creates its journal files with the same mode."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
    path.chmod(0o600)  # an older file may have been readable by others


def _configure_connection(connection: Any, _record: object) -> None:  # DB-API connection
    cursor = connection.cursor()
    # A wrong key is reported once, by `open_database`, not also on stderr.
    cursor.execute("PRAGMA cipher_log_level = NONE")
    cursor.execute("PRAGMA foreign_keys = ON")
    # Deleted data (an old API key) is overwritten, not left in free pages.
    cursor.execute("PRAGMA secure_delete = ON")
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.close()
