from collections.abc import Callable

import pytest

from vt_api.adapters.secret_box import SecretBox, SecretBoxError, derive_key

MASTER = bytes(range(32))


def test_keys_are_derived_per_purpose() -> None:
    sqlcipher, columns = derive_key(MASTER, "sqlcipher"), derive_key(MASTER, "columns")

    assert len(sqlcipher) == len(columns) == 32
    assert sqlcipher != columns != MASTER
    assert derive_key(MASTER, "columns") == columns


def test_seal_and_open() -> None:
    box = SecretBox(derive_key(MASTER, "columns"))

    sealed = box.seal("sk-fake-1234", "row 1")

    assert box.open(sealed, "row 1") == "sk-fake-1234"
    assert b"sk-fake" not in sealed
    assert box.seal("sk-fake-1234", "row 1") != sealed  # a fresh nonce every time


def _flip_last_byte(sealed: bytes) -> bytes:
    return sealed[:-1] + bytes([sealed[-1] ^ 1])


def _same(sealed: bytes) -> bytes:
    return sealed


@pytest.mark.parametrize(
    ("tamper", "context", "key"),
    [
        pytest.param(_same, "row 2", MASTER, id="moved to another row"),
        pytest.param(_same, "row 1", bytes(32), id="another key"),
        pytest.param(_flip_last_byte, "row 1", MASTER, id="damaged"),
        pytest.param(lambda sealed: b"\x02" + sealed[1:], "row 1", MASTER, id="unknown version"),
        pytest.param(lambda sealed: sealed[:20], "row 1", MASTER, id="truncated"),
    ],
)
def test_anything_else_does_not_open(
    tamper: Callable[[bytes], bytes], context: str, key: bytes
) -> None:
    sealed = SecretBox(derive_key(MASTER, "columns")).seal("sk-fake-1234", "row 1")

    with pytest.raises(SecretBoxError):
        SecretBox(derive_key(key, "columns")).open(tamper(sealed), context)
