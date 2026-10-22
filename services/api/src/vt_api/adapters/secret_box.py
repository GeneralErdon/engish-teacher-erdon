"""Keys derived from the master key, and AES-256-GCM for secret columns.

Two layers protect an API key in SQLite: SQLCipher encrypts the whole file, and the column
itself holds AES-GCM ciphertext. The second layer does not depend on the database engine, so
saved keys stay encrypted on Postgres too. Each purpose gets its own key (HKDF), and every
ciphertext is bound to its row: copied to another provider or URL, it no longer decrypts.
"""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_VERSION = b"\x01"
_NONCE_BYTES = 12
_TAG_BYTES = 16


class SecretBoxError(Exception):
    """A sealed value cannot be opened: another key, another row, or damaged data."""


def derive_key(master: bytes, purpose: str) -> bytes:
    """A 256-bit key for one purpose (`"sqlcipher"`, `"columns"`), from the master key."""
    hkdf = HKDF(algorithm=SHA256(), length=32, salt=None, info=f"voice-tutor/{purpose}".encode())
    return hkdf.derive(master)


class SecretBox:
    def __init__(self, key: bytes) -> None:
        self._aead = AESGCM(key)

    def seal(self, plaintext: str, context: str) -> bytes:
        """`version | nonce | ciphertext+tag`. `context` (e.g. the row's identity) is
        authenticated: `open` needs the same one."""
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._aead.encrypt(nonce, plaintext.encode(), context.encode())
        return _VERSION + nonce + ciphertext

    def open(self, sealed: bytes, context: str) -> str:
        if sealed[:1] != _VERSION or len(sealed) < 1 + _NONCE_BYTES + _TAG_BYTES:
            msg = "not a sealed value"
            raise SecretBoxError(msg)
        nonce, ciphertext = sealed[1 : 1 + _NONCE_BYTES], sealed[1 + _NONCE_BYTES :]
        try:
            return self._aead.decrypt(nonce, ciphertext, context.encode()).decode()
        except InvalidTag as error:
            msg = "wrong key or context, or damaged data"
            raise SecretBoxError(msg) from error
