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

A repository listed in `single_file_repos` (whisper.cpp's GGML files) holds models that are
single files, `org/name/file`, each fetched and removed alone. The marker then holds the model id
being downloaded (an empty one, from an older api, means the whole repository), and every
removal there spares the files that are complete: only orphan `*.incomplete` blobs, dangling
snapshot links and the marker go, and the folder goes once no snapshot file is left and no
download of ours writes into it.
"""

import asyncio
import logging
import os
import shutil
import stat
import sys
import time
from collections.abc import Awaitable, Callable, Collection, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

import anyio
from huggingface_hub import HfApi
from huggingface_hub.file_download import repo_folder_name

from vt_api.domain.speech import SpeechSettingsError, split_model_id
from vt_contracts.speech import DownloadProgress

logger = logging.getLogger(__name__)

TERMINATE_GRACE_S = 5.0
"""How long a terminated worker may take to exit before it is killed."""
STALE_AFTER_S = 600.0
"""How long a half-written model must have gone unchanged before `cleanup()` removes it."""
DOWNLOADING_MARKER = ".voice-tutor-downloading"
"""In the model's folder from before the worker starts until it succeeds. It holds the model
id being downloaded; empty means the whole repository."""

_HUB_TIMEOUT_S = 30.0
_MB = 1_000_000
_WORKER_ENV = {"HF_HUB_DISABLE_XET": "1", "HF_HUB_DISABLE_PROGRESS_BARS": "1"}
"""Plain HTTP (see above), and an stderr that holds warnings and the error only."""


async def hub_total_size(model_id: str) -> int:
    """The bytes of every file in the model's main revision, or of its one file, from the
    Hugging Face API.

    Raises `SpeechSettingsError` (502) for a file the repository does not list: the worker
    would fetch nothing and succeed, and the model would count as downloaded without its file.
    """
    repo_id, only = split_model_id(model_id)
    info = await anyio.to_thread.run_sync(
        lambda: HfApi().model_info(repo_id, files_metadata=True, timeout=_HUB_TIMEOUT_S),
        abandon_on_cancel=True,
    )
    files = [file for file in info.siblings or [] if only is None or file.rfilename == only]
    if only is not None and not files:  # absent, not merely empty: the listing says
        raise SpeechSettingsError(502, f"Hugging Face has no file {only} in {repo_id}.")
    return sum(file.size or 0 for file in files)


class HfModelFiles:
    """Downloads into `cache_dir`, one model at a time. Building one does file I/O: it
    creates `cache_dir` and runs `cleanup()`."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        single_file_repos: Collection[str] = (),
        total_size: Callable[[str], Awaitable[int]] = hub_total_size,
        worker: Sequence[str] = (sys.executable, "-m", "vt_api.adapters.model_download"),
        poll_s: float = 0.5,
    ) -> None:
        self._cache_dir = cache_dir
        self._single_file_folders = {
            repo_folder_name(repo_id=repo_id, repo_type="model") for repo_id in single_file_repos
        }
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
        file = split_model_id(model_id)[1]
        try:
            if file is None:
                await anyio.to_thread.run_sync(_delete, repo)
            else:
                await anyio.to_thread.run_sync(_delete_file, repo, file)
        except OSError as error:
            raise SpeechSettingsError(
                500, f"Could not delete {model_id}: {error.strerror or error}"
            ) from error

    async def incomplete(self) -> set[str]:
        return await anyio.to_thread.run_sync(self._partial_models)

    async def present(self, model_ids: Collection[str]) -> set[str]:
        return await anyio.to_thread.run_sync(self._present, model_ids)

    async def snapshot_path(self, model_id: str) -> str | None:
        return await anyio.to_thread.run_sync(self._snapshot_path, model_id)

    def cleanup(self) -> None:
        quiet_since = time.time() - STALE_AFTER_S
        for repo in self._cache_dir.glob("models--*"):
            if _is_partial(repo) and _last_change(repo) < quiet_since:
                self._remove_partial(repo)

    def _partial_models(self) -> set[str]:
        return {
            _marked_model(repo) or _model_id(repo)
            for repo in self._cache_dir.glob("models--*")
            if _is_partial(repo)
        }

    def _present(self, model_ids: Collection[str]) -> set[str]:
        downloading = {_marked_model(repo) for repo in self._cache_dir.glob("models--*")}
        return {
            model_id
            for model_id in model_ids
            if model_id not in downloading and self._snapshot_path(model_id) is not None
        }

    def _snapshot_path(self, model_id: str) -> str | None:
        file = split_model_id(model_id)[1]
        if file is None:
            return None
        repo = self._repo(model_id)
        snapshots = repo / "snapshots"
        with suppress(OSError):
            revision = (repo / "refs" / "main").read_text().strip()
            if (snapshots / revision / file).is_file():
                return (snapshots / revision / file).relative_to(self._cache_dir).as_posix()
        for snapshot in sorted(snapshots.glob("*")):  # the revision moved since it was fetched
            if (snapshot / file).is_file():
                return (snapshot / file).relative_to(self._cache_dir).as_posix()
        return None

    def _repo(self, model_id: str) -> Path:
        """`models--{org}--{name}`. Raises `ValueError` for an id the Hub would refuse, so no
        id names a folder outside the cache or another model's."""
        return self._cache_dir / repo_folder_name(
            repo_id=split_model_id(model_id)[0], repo_type="model"
        )

    def _holds_files(self, repo: Path) -> bool:
        """Whether the folder's models are single files: its siblings must survive a removal."""
        return repo.name in self._single_file_folders or _marked_model(repo) is not None

    def _remove_partial(self, repo: Path) -> None:
        if self._holds_files(repo):
            _remove_partial_files(repo)
        else:
            _remove_partial(repo)

    async def _discard(self, process: asyncio.subprocess.Process | None, repo: Path) -> None:
        """End the worker, if it started, then remove what it wrote."""
        if process is not None:
            await _stop(process)
        await anyio.to_thread.run_sync(self._remove_partial, repo)

    async def _size(self, model_id: str) -> int:
        try:
            return await self._total_size(model_id)
        except SpeechSettingsError:  # it says what is wrong already
            raise
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
            await anyio.to_thread.run_sync(_mark_downloading, repo, model_id)
            baseline = (
                await anyio.to_thread.run_sync(_bytes_on_disk, repo)
                if split_model_id(model_id)[1] is not None
                else 0
            )
            process = await asyncio.create_subprocess_exec(
                *self._worker,
                model_id,
                str(self._cache_dir),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **_WORKER_ENV},
            )
            stderr = await self._watch(process, model_id, repo, total, baseline)
        except BaseException:  # cancelled: the worker must not outlive the download
            await asyncio.shield(self._discard(process, repo))
            raise
        if process.returncode != 0:
            await anyio.to_thread.run_sync(self._remove_partial, repo)
            text = stderr.decode(errors="replace")
            logger.warning("Downloading %s failed:\n%s", model_id, text)
            lines = text.strip().splitlines()
            reason = lines[-1] if lines else f"the worker exited with code {process.returncode}"
            raise SpeechSettingsError(502, f"Downloading {model_id} failed: {reason}")
        await anyio.to_thread.run_sync(_unmark, repo)

    async def _watch(
        self,
        process: asyncio.subprocess.Process,
        model_id: str,
        repo: Path,
        total: int,
        baseline: int,
    ) -> bytes:
        """Wait for the worker to exit, counting its bytes on disk (beyond `baseline`, those
        of the folder's other files) meanwhile. Returns its stderr."""
        async with asyncio.TaskGroup() as group:
            exited = group.create_task(process.communicate())
            done = 0
            while not exited.done():
                on_disk = await anyio.to_thread.run_sync(_bytes_on_disk, repo)
                new_bytes = max(on_disk - baseline, 0)
                done = max(done, min(new_bytes, total))  # never backwards, never past the total
                self._progress = (model_id, DownloadProgress(done_bytes=done, total_bytes=total))
                await asyncio.wait({exited}, timeout=self._poll_s)
        return exited.result()[1]


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


def _mark_downloading(repo: Path, model_id: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / DOWNLOADING_MARKER).write_text(model_id)


def _marked_model(repo: Path) -> str | None:
    """The single-file model id the marker names; `None` for no marker or a whole repository."""
    try:
        text = (repo / DOWNLOADING_MARKER).read_text().strip()
        return text if split_model_id(text)[1] is not None else None
    except OSError, ValueError:
        return None


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


def _snapshot_links(repo: Path) -> list[Path]:
    """Every file of every snapshot, dangling links included."""
    return [link for snapshot in (repo / "snapshots").glob("*") for link in snapshot.glob("*")]


def _remove_partial_files(repo: Path) -> None:
    """Remove what an unfinished single-file download left, sparing the complete files: the
    orphan blobs, the links to them, the marker, and the folder when nothing else is in it."""
    blobs = repo / "blobs"
    for part in blobs.glob("*.incomplete"):
        if not (blobs / part.name.split(".", 1)[0]).exists():
            part.unlink(missing_ok=True)
    for link in _snapshot_links(repo):
        if link.is_symlink() and not link.exists():
            link.unlink(missing_ok=True)
    (repo / DOWNLOADING_MARKER).unlink(missing_ok=True)
    _remove_if_empty(repo)


def _remove_if_empty(repo: Path) -> None:
    """Remove the folder once no snapshot file is left, unless our marker says a download is
    writing into it: the file it fetches has no link yet."""
    if (repo / DOWNLOADING_MARKER).exists():
        return
    if not any(link.is_file() for link in _snapshot_links(repo)):
        shutil.rmtree(repo, ignore_errors=True)


def _delete_file(repo: Path, file: str) -> None:
    """Remove one file's links in every snapshot and the blobs no other link uses."""
    blob_names = set()
    for link in _snapshot_links(repo):
        if link.name == file:
            if link.is_symlink():
                blob_names.add(link.readlink().name)
            link.unlink()
    in_use = {link.readlink().name for link in _snapshot_links(repo) if link.is_symlink()}
    for name in blob_names - in_use:
        (repo / "blobs" / name).unlink(missing_ok=True)
    _remove_if_empty(repo)
