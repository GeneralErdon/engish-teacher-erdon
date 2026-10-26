"""Speech models in the Hugging Face cache folder that Speaches reads.

`huggingface_hub` neither reports progress to its caller nor stops a download, so a child
process (`vt_api.adapters.model_download`) downloads, the api ends it to cancel, and progress
is the bytes on disk. Xet is off in the child: with Xet, `huggingface_hub` 2.2 keeps blobs in
a store shared by every repo and links them from the repo folder, so deleting a model's folder
would not free its space. Over plain HTTP every byte lands in the repo's `blobs/`, as
`*.incomplete` until the file is complete.

`snapshot_download` records the revision (`refs/main`) before it fetches the files, so a download
also marks the model's folder until the worker succeeds. `cleanup()` removes a marked folder, or
one with an unfinished blob, only once nothing has written to it for `STALE_AFTER_S`: a model
Speaches is downloading at that moment is left alone. Until then `incomplete()` names it, so the
api does not count it as installed even if Speaches lists it.
"""

import asyncio
import logging
import os
import shutil
import stat
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

import anyio
from huggingface_hub import HfApi
from huggingface_hub.file_download import repo_folder_name

from vt_api.domain.speech import SpeechSettingsError
from vt_contracts.speech import DownloadProgress

logger = logging.getLogger(__name__)

TERMINATE_GRACE_S = 5.0
"""How long a terminated worker may take to exit before it is killed."""
STALE_AFTER_S = 600.0
"""How long a half-written model must have gone unchanged before `cleanup()` removes it."""
DOWNLOADING_MARKER = ".voice-tutor-downloading"
"""In the model's folder from before the worker starts until it succeeds."""

_HUB_TIMEOUT_S = 30.0
_MB = 1_000_000
_WORKER_ENV = {"HF_HUB_DISABLE_XET": "1", "HF_HUB_DISABLE_PROGRESS_BARS": "1"}
"""Plain HTTP (see above), and an stderr that holds warnings and the error only."""


async def hub_total_size(model_id: str) -> int:
    """The bytes of every file in the model's main revision, from the Hugging Face API."""
    info = await anyio.to_thread.run_sync(
        lambda: HfApi().model_info(model_id, files_metadata=True, timeout=_HUB_TIMEOUT_S),
        abandon_on_cancel=True,
    )
    return sum(file.size or 0 for file in info.siblings or [])


class HfModelFiles:
    """Downloads into `cache_dir`, one model at a time. Building one does file I/O: it
    creates `cache_dir` and runs `cleanup()`."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        total_size: Callable[[str], Awaitable[int]] = hub_total_size,
        worker: Sequence[str] = (sys.executable, "-m", "vt_api.adapters.model_download"),
        poll_s: float = 0.5,
    ) -> None:
        self._cache_dir = cache_dir
        self._total_size = total_size
        self._worker = tuple(worker)
        self._poll_s = poll_s
        self._task: asyncio.Task[Any] | None = None
        self._progress: tuple[str, DownloadProgress] | None = None
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.cleanup()

    def progress(self) -> tuple[str, DownloadProgress] | None:
        return self._progress

    async def download(self, model_id: str) -> None:
        repo = self._repo(model_id)
        self._task = asyncio.current_task()
        self._progress = (model_id, DownloadProgress(done_bytes=0, total_bytes=None))
        try:
            total = await self._size(model_id)
            self._progress = (model_id, DownloadProgress(done_bytes=0, total_bytes=total))
            await self._check_space(model_id, total)
            await self._run_worker(model_id, repo, total)
        finally:
            self._task = None
            self._progress = None

    async def cancel(self) -> None:
        task = self._task
        if task is None:
            return
        if not task.cancelling():  # a second cancel would cut the first one's cleanup short
            task.cancel()
        await asyncio.wait({task})

    async def delete(self, model_id: str) -> None:
        repo = self._repo(model_id)
        try:
            await anyio.to_thread.run_sync(_delete, repo)
        except OSError as error:
            raise SpeechSettingsError(
                500, f"Could not delete {model_id}: {error.strerror or error}"
            ) from error

    async def incomplete(self) -> set[str]:
        return await anyio.to_thread.run_sync(self._partial_models)

    def cleanup(self) -> None:
        quiet_since = time.time() - STALE_AFTER_S
        for repo in self._cache_dir.glob("models--*"):
            if _is_partial(repo) and _last_change(repo) < quiet_since:
                _remove_partial(repo)

    def _partial_models(self) -> set[str]:
        return {_model_id(repo) for repo in self._cache_dir.glob("models--*") if _is_partial(repo)}

    def _repo(self, model_id: str) -> Path:
        """`models--{org}--{name}`. Raises `ValueError` for an id the Hub would refuse, so no
        id names a folder outside the cache or another model's."""
        return self._cache_dir / repo_folder_name(repo_id=model_id, repo_type="model")

    async def _size(self, model_id: str) -> int:
        try:
            return await self._total_size(model_id)
        except Exception as error:
            raise SpeechSettingsError(
                502, f"Could not get the size of {model_id} from Hugging Face: {error}"
            ) from error

    async def _check_space(self, model_id: str, total: int) -> None:
        """Refuse a download that would not fit with 10 % to spare."""
        needed = total + total // 10
        free = (await anyio.to_thread.run_sync(shutil.disk_usage, self._cache_dir)).free
        if free < needed:
            raise SpeechSettingsError(
                507,
                f"Not enough disk space to download {model_id}: it needs {-(-needed // _MB)} MB "
                f"and {free // _MB} MB are free.",
            )

    async def _run_worker(self, model_id: str, repo: Path, total: int) -> None:
        process: asyncio.subprocess.Process | None = None
        try:
            await anyio.to_thread.run_sync(_mark_downloading, repo)
            process = await asyncio.create_subprocess_exec(
                *self._worker,
                model_id,
                str(self._cache_dir),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **_WORKER_ENV},
            )
            stderr = await self._watch(process, model_id, repo, total)
        except BaseException:  # cancelled: the worker must not outlive the download
            await asyncio.shield(_discard(process, repo))
            raise
        if process.returncode != 0:
            await anyio.to_thread.run_sync(_remove_partial, repo)
            text = stderr.decode(errors="replace")
            logger.warning("Downloading %s failed:\n%s", model_id, text)
            lines = text.strip().splitlines()
            reason = lines[-1] if lines else f"the worker exited with code {process.returncode}"
            raise SpeechSettingsError(502, f"Downloading {model_id} failed: {reason}")
        await anyio.to_thread.run_sync(_unmark, repo)

    async def _watch(
        self, process: asyncio.subprocess.Process, model_id: str, repo: Path, total: int
    ) -> bytes:
        """Wait for the worker to exit, counting its bytes on disk meanwhile. Returns its
        stderr."""
        async with asyncio.TaskGroup() as group:
            exited = group.create_task(process.communicate())
            done = 0
            while not exited.done():
                on_disk = await anyio.to_thread.run_sync(_bytes_on_disk, repo)
                done = max(done, min(on_disk, total))  # never backwards, never past the total
                self._progress = (model_id, DownloadProgress(done_bytes=done, total_bytes=total))
                await asyncio.wait({exited}, timeout=self._poll_s)
        return exited.result()[1]


async def _discard(process: asyncio.subprocess.Process | None, repo: Path) -> None:
    """End the worker, if it started, then remove the model's folder."""
    if process is not None:
        await _stop(process)
    await anyio.to_thread.run_sync(_remove_partial, repo)


async def _stop(process: asyncio.subprocess.Process) -> None:
    """Terminate the worker, and kill it if it is still running after `TERMINATE_GRACE_S`."""
    with suppress(ProcessLookupError):  # it has exited already
        process.terminate()
    try:
        await asyncio.wait_for(process.communicate(), TERMINATE_GRACE_S)
    except TimeoutError:
        with suppress(ProcessLookupError):
            process.kill()
        await process.communicate()


def _mark_downloading(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / DOWNLOADING_MARKER).touch()


def _unmark(repo: Path) -> None:
    (repo / DOWNLOADING_MARKER).unlink(missing_ok=True)


def _bytes_on_disk(repo: Path) -> int:
    """The size of the repo's blobs, those still being written included."""
    size = 0
    with suppress(FileNotFoundError):  # no blobs yet
        for blob in (repo / "blobs").iterdir():
            with suppress(FileNotFoundError):  # renamed when complete, since it was listed
                size += blob.stat().st_size
    return size


def _is_partial(repo: Path) -> bool:
    """A download of ours did not finish, or a blob was never finished.

    An attempt writes `<etag>.<uuid8>.incomplete` (older versions `<etag>.incomplete`), so a
    killed attempt can leave one beside the `<etag>` a later attempt finished: that model is
    complete.
    """
    blobs = repo / "blobs"
    return (repo / DOWNLOADING_MARKER).exists() or any(
        not (blobs / part.name.split(".", 1)[0]).exists() for part in blobs.glob("*.incomplete")
    )


def _model_id(repo: Path) -> str:
    """`models--{org}--{name}` back to `{org}/{name}`: the Hub refuses `--` in an id."""
    return repo.name.removeprefix("models--").replace("--", "/")


def _last_change(repo: Path) -> float:
    """When a file under `repo` was last modified (0 when there is none)."""
    newest = 0.0
    for path in repo.rglob("*"):
        with suppress(FileNotFoundError):  # removed since it was listed
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode):
                newest = max(newest, info.st_mtime)
    return newest


def _remove_partial(repo: Path) -> None:
    """Best effort: a leftover must not stop the api from starting, nor hide why a download
    ended."""
    shutil.rmtree(repo, ignore_errors=True)


def _delete(repo: Path) -> None:
    with suppress(FileNotFoundError):
        shutil.rmtree(repo)
