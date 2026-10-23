import base64
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from vt_api.adapters.secret_key import (
    KEYRING_SERVICE,
    KEYRING_USERNAME,
    SecretKeyError,
    generate,
    load_master_key,
    usable_keyring,
)

KEY = bytes(range(32))
ENCODED = base64.b64encode(KEY).decode()


@dataclass
class MemoryKeyring:
    priority: int = 5
    entries: dict[tuple[str, str], str] = field(default_factory=dict)

    def get_password(self, service: str, username: str) -> str | None:
        return self.entries.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.entries[service, username] = password


def test_the_environment_wins(tmp_path: Path) -> None:
    (tmp_path / "secret.key").write_text(generate())

    key = load_master_key(
        environment=f"  {ENCODED}\n", key_file=tmp_path / "secret.key", keyring=MemoryKeyring()
    )

    assert (key.value, key.source, key.where) == (KEY, "environment", "VT_SECRET_KEY")
    assert ENCODED not in repr(key)


@pytest.mark.parametrize("bad", ["not base64!", base64.b64encode(b"short").decode()])
def test_a_bad_key_says_how_to_make_one(tmp_path: Path, bad: str) -> None:
    with pytest.raises(SecretKeyError, match="VT_SECRET_KEY must be 32 random bytes") as error:
        load_master_key(environment=bad, key_file=tmp_path / "k", keyring=None)

    assert "generate()" in str(error.value)


def test_an_existing_key_file_wins_over_the_keyring(tmp_path: Path) -> None:
    path = tmp_path / "secret.key"
    path.write_text(ENCODED + "\n")
    keyring = MemoryKeyring()

    key = load_master_key(environment=None, key_file=path, keyring=keyring)

    assert (key.value, key.source, key.where) == (KEY, "file", str(path))
    assert keyring.entries == {}


def test_a_damaged_key_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "secret.key"
    path.write_text("garbage")

    with pytest.raises(SecretKeyError, match=str(path)):
        load_master_key(environment=None, key_file=path, keyring=None)


def test_the_keyring_keeps_a_new_key(tmp_path: Path) -> None:
    keyring = MemoryKeyring()

    first = load_master_key(environment=None, key_file=tmp_path / "secret.key", keyring=keyring)
    again = load_master_key(environment=None, key_file=tmp_path / "secret.key", keyring=keyring)

    assert first.source == "keyring"
    assert first.value == again.value
    assert len(first.value) == 32
    assert base64.b64decode(keyring.entries[KEYRING_SERVICE, KEYRING_USERNAME]) == first.value
    assert not (tmp_path / "secret.key").exists()  # nothing on disk


def test_without_a_keyring_a_private_key_file_is_created(tmp_path: Path) -> None:
    path = tmp_path / "private" / "secret.key"

    first = load_master_key(environment=None, key_file=path, keyring=None)
    again = load_master_key(environment=None, key_file=path, keyring=None)

    assert first.source == "file"
    assert first.value == again.value
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize(("priority", "usable"), [(5, True), (0, False), (-1, False)])
def test_only_a_real_keyring_is_used(
    monkeypatch: pytest.MonkeyPatch, priority: int, usable: bool
) -> None:
    backend = MemoryKeyring(priority=priority)
    monkeypatch.setattr("keyring.get_keyring", lambda: backend)

    assert (usable_keyring() is backend) == usable


def test_tests_never_reach_the_real_keyring() -> None:
    assert usable_keyring() is None  # conftest selects keyring's null backend
