"""Small JSON files that may hold secrets: readable only by their owner, replaced atomically."""

import os
from pathlib import Path

import anyio

_FILE_MODE = 0o600
_DIR_MODE = 0o700


async def read_or_none(path: Path) -> bytes | None:
    try:
        return await anyio.Path(path).read_bytes()
    except FileNotFoundError:
        return None


async def write_private(path: Path, text: str) -> None:
    await anyio.to_thread.run_sync(_write, path, text)


async def delete(path: Path) -> None:
    await anyio.Path(path).unlink(missing_ok=True)


def _write(path: Path, text: str) -> None:
    """Write a private temporary file next to the target, then rename it over the target."""
    path.parent.mkdir(mode=_DIR_MODE, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    # Created with mode 0600 from the start, so the content is never readable by others.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FILE_MODE)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())
    tmp.replace(path)
