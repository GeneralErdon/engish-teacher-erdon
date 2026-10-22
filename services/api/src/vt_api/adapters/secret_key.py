"""The master key that encrypts the database: 32 random bytes, never stored in the database.

Where it comes from, in this order:

1. `VT_SECRET_KEY` (base64): servers, Docker secrets, or one key shared by several installs.
2. An existing key file (`VT_SECRET_KEY_FILE`): created earlier where there was no keyring.
3. The OS keyring (GNOME Keyring or KWallet, Windows Credential Manager, macOS Keychain):
   on a desktop, created on first start, so the key never touches the disk in the clear.
4. A new key file, mode 0600: containers and headless machines have no keyring.

Losing the key loses what the database holds (saved API keys): it cannot be recovered.
"""

import base64
import binascii
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

import keyring as os_keyring

KEY_BYTES = 32
KEYRING_SERVICE = "voice-tutor"
KEYRING_USERNAME = "master-key"

type KeySource = Literal["environment", "file", "keyring"]


class SecretKeyError(Exception):
    """The configured key is unusable; the message says how to fix it."""


class Keyring(Protocol):
    """The subset of `keyring.backend.KeyringBackend` used here."""

    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...


@dataclass(frozen=True, slots=True)
class MasterKey:
    value: bytes = field(repr=False)
    source: KeySource
    where: str
    """The variable, file or keyring entry it came from (never the key itself)."""


def usable_keyring() -> Keyring | None:
    """The OS keyring, or `None` when there is none (containers, CI, headless servers)."""
    backend = os_keyring.get_keyring()
    # The `fail` and `null` backends stand in for "no keyring" with priority 0 and -1.
    return backend if backend.priority > 0 else None


def generate() -> str:
    """A new key, base64: what `VT_SECRET_KEY` expects."""
    return base64.b64encode(secrets.token_bytes(KEY_BYTES)).decode()


def load_master_key(
    *, environment: str | None, key_file: Path, keyring: Keyring | None
) -> MasterKey:
    """Find the key, or create one. Blocking (files, D-Bus): run it in a worker thread."""
    if environment:
        return MasterKey(_decode(environment, "VT_SECRET_KEY"), "environment", "VT_SECRET_KEY")
    if key_file.exists():
        return _from_file(key_file)
    if keyring is not None:
        return _from_keyring(keyring)
    return _new_file(key_file)


def _decode(encoded: str, where: str) -> bytes:
    try:
        key = base64.b64decode(encoded.strip(), validate=True)
    except binascii.Error:
        key = b""
    if len(key) != KEY_BYTES:
        msg = (
            f"{where} must be {KEY_BYTES} random bytes in base64. Create one with: "
            'uv run python -c "from vt_api.adapters.secret_key import generate; print(generate())"'
        )
        raise SecretKeyError(msg)
    return key


def _from_file(path: Path) -> MasterKey:
    return MasterKey(_decode(path.read_text(encoding="ascii"), str(path)), "file", str(path))


def _from_keyring(keyring: Keyring) -> MasterKey:
    where = f"keyring: service {KEYRING_SERVICE}, user {KEYRING_USERNAME}"
    # A keyring that exists but fails (locked, denied) is an error, never a reason to fall back
    # to a new key: the database was encrypted with the one in the keyring.
    stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    if stored is None:
        stored = generate()
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, stored)
    return MasterKey(_decode(stored, where), "keyring", where)


def _new_file(path: Path) -> MasterKey:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = generate()
    # O_EXCL: never overwrite a key; mode 0600 from the first byte.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as file:
        file.write(encoded + "\n")
    return MasterKey(base64.b64decode(encoded), "file", str(path))
