"""Model files in a Hugging Face cache folder, downloaded by a fake worker.

The fake writes the Hugging Face layout a few bytes at a time, as `huggingface_hub` does over
plain HTTP. Nothing here touches the network, the real worker command or `HfApi`.
"""

import asyncio
import os
import shutil
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from types import SimpleNamespace

import huggingface_hub
import pytest

from vt_api.adapters import model_download, model_files
from vt_api.adapters.model_files import DOWNLOADING_MARKER, HfModelFiles
from vt_api.domain.speech import SpeechSettingsError
from vt_api.ports.speech import ModelFiles

MODEL = "org/m"
REPO = "models--org--m"
TOTAL = 1000
MB = 1_000_000

# Arguments: steps, bytes per step, seconds between steps, mode; then the model id and the
# cache folder, as the real worker gets them. It refuses to run with Xet on.
FAKE_WORKER = """\
import os
import signal
import sys
import time
from pathlib import Path

steps, chunk, pause, mode, model_id, cache_dir = sys.argv[1:]
if os.environ.get("HF_HUB_DISABLE_XET") != "1":
    sys.exit("Xet must be off")
if mode == "stubborn":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
repo = Path(cache_dir) / ("models--" + model_id.replace("/", "--"))
(repo / "refs").mkdir(parents=True, exist_ok=True)
(repo / "refs" / "main").write_text("0" * 40)
part = repo / "blobs" / "f00d.1a2b3c4d.incomplete"
for _ in range(int(steps)):
    part.parent.mkdir(parents=True, exist_ok=True)  # alive after a cancel, it would show
    with part.open("ab") as blob:
        blob.write(b"x" * int(chunk))
    time.sleep(float(pause))
if mode == "fail":
    sys.exit("Connection reset by peer")
part.rename(repo / "blobs" / "f00d")
"""


windows_has_no_sigterm = pytest.mark.skipif(
    sys.platform == "win32", reason="the worker ignores SIGTERM, which Windows does not have"
)


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    return tmp_path / "hub"


def fake_worker(
    tmp_path: Path, *, steps: int = 10, pause: float = 0.03, mode: str = "ok"
) -> tuple[str, ...]:
    """Writes TOTAL bytes in `steps` steps, `pause` seconds apart."""
    script = tmp_path / "fake_worker.py"
    script.write_text(FAKE_WORKER)
    return (sys.executable, str(script), str(steps), str(TOTAL // steps), str(pause), mode)


def sized(total: int) -> Callable[[str], Awaitable[int]]:
    async def total_size(_model_id: str) -> int:
        return total

    return total_size


def hf_files(cache: Path, worker: Sequence[str]) -> HfModelFiles:
    return HfModelFiles(cache, total_size=sized(TOTAL), worker=worker, poll_s=0.01)


def make_repo(
    cache: Path, model_id: str, *, blobs: Sequence[str] = ("f00d",), marked: bool = False
) -> Path:
    repo = cache / ("models--" + model_id.replace("/", "--"))
    (repo / "blobs").mkdir(parents=True)
    for name in blobs:
        (repo / "blobs" / name).write_bytes(b"x" * 10)
    (repo / "refs").mkdir()
    (repo / "refs" / "main").write_text("0" * 40)
    if marked:
        (repo / DOWNLOADING_MARKER).touch()
    return repo


def gone_quiet(repo: Path) -> Path:
    """Dates every file in `repo` back past the staleness threshold."""
    then = time.time() - model_files.STALE_AFTER_S - 60
    for path in [repo, *repo.rglob("*")]:
        os.utime(path, (then, then))
    return repo


async def until_bytes_on_disk(files: HfModelFiles) -> None:
    """Polls: the bytes come from another process, which signals nothing."""
    async with asyncio.timeout(10):
        while True:
            if (current := files.progress()) is not None and current[1].done_bytes > 0:
                return
            await asyncio.sleep(0.005)


async def test_progress_counts_bytes_on_disk(tmp_path: Path, cache: Path) -> None:
    files = hf_files(cache, fake_worker(tmp_path))
    download = asyncio.create_task(files.download(MODEL))
    seen: list[int] = []
    while not download.done():
        if (current := files.progress()) is not None:
            model_id, progress = current
            assert model_id == MODEL
            assert progress.total_bytes in (None, TOTAL)  # None until the size is known
            seen.append(progress.done_bytes)
        await asyncio.sleep(0.005)
    await download

    assert files.progress() is None
    assert seen == sorted(seen)
    assert len(set(seen)) >= 3
    assert max(seen) <= TOTAL
    assert (cache / REPO / "blobs" / "f00d").stat().st_size == TOTAL


async def test_a_download_marks_its_folder_until_it_succeeds(tmp_path: Path, cache: Path) -> None:
    files = hf_files(cache, fake_worker(tmp_path))
    download = asyncio.create_task(files.download(MODEL))
    await until_bytes_on_disk(files)

    assert (cache / REPO / DOWNLOADING_MARKER).exists()
    await download
    assert not (cache / REPO / DOWNLOADING_MARKER).exists()
    assert (cache / REPO / "blobs" / "f00d").exists()


async def test_cancel_stops_the_worker_and_removes_partial_files(
    tmp_path: Path, cache: Path
) -> None:
    files = hf_files(cache, fake_worker(tmp_path, steps=1000, pause=0.01))
    download = asyncio.create_task(files.download(MODEL))
    await until_bytes_on_disk(files)

    await files.cancel()

    with pytest.raises(asyncio.CancelledError):
        await download
    assert files.progress() is None
    assert not (cache / REPO).exists()
    await asyncio.sleep(0.1)  # ten steps: a worker still running would bring the folder back
    assert not (cache / REPO).exists()
    await files.cancel()  # nothing left to cancel


@windows_has_no_sigterm
async def test_a_worker_that_ignores_terminate_is_killed(
    tmp_path: Path, cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(model_files, "TERMINATE_GRACE_S", 0.1)
    files = hf_files(cache, fake_worker(tmp_path, steps=1000, pause=0.01, mode="stubborn"))
    download = asyncio.create_task(files.download(MODEL))
    await until_bytes_on_disk(files)

    async with asyncio.timeout(3):  # left alone, the worker would write for 10 s
        await files.cancel()

    assert download.cancelled()
    await asyncio.sleep(0.1)
    assert not (cache / REPO).exists()


@windows_has_no_sigterm
async def test_a_second_cancel_waits_for_the_first(
    tmp_path: Path, cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(model_files, "TERMINATE_GRACE_S", 0.2)
    files = hf_files(cache, fake_worker(tmp_path, steps=1000, pause=0.01, mode="stubborn"))
    download = asyncio.create_task(files.download(MODEL))
    await until_bytes_on_disk(files)
    first = asyncio.create_task(files.cancel())
    await asyncio.sleep(0.05)  # the first cancel waits for the worker to exit

    await files.cancel()

    assert download.cancelled()
    assert not (cache / REPO).exists()
    await first


async def test_refuses_when_the_disk_is_too_small(
    tmp_path: Path, cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: SimpleNamespace(free=100 * MB))
    files = HfModelFiles(cache, total_size=sized(1000 * MB), worker=fake_worker(tmp_path))

    with pytest.raises(SpeechSettingsError) as caught:
        await files.download(MODEL)

    assert caught.value.status == 507
    assert caught.value.message == (
        "Not enough disk space to download org/m: it needs 1100 MB and 100 MB are free."
    )
    assert not (cache / REPO).exists()  # the worker never ran
    assert files.progress() is None


async def test_a_failing_worker_is_an_error(tmp_path: Path, cache: Path) -> None:
    files = hf_files(cache, fake_worker(tmp_path, steps=2, mode="fail"))

    with pytest.raises(SpeechSettingsError) as caught:
        await files.download(MODEL)

    assert caught.value.status == 502
    assert caught.value.message == "Downloading org/m failed: Connection reset by peer"
    assert not (cache / REPO).exists()
    assert files.progress() is None


async def test_an_unreachable_hub_is_an_error(tmp_path: Path, cache: Path) -> None:
    async def unreachable(_model_id: str) -> int:
        raise OSError("Network is unreachable")

    files = HfModelFiles(cache, total_size=unreachable, worker=fake_worker(tmp_path))

    with pytest.raises(SpeechSettingsError) as caught:
        await files.download(MODEL)

    assert caught.value.status == 502
    assert caught.value.message == (
        "Could not get the size of org/m from Hugging Face: Network is unreachable"
    )
    assert files.progress() is None


def test_cleanup_removes_half_written_repos_once_quiet(cache: Path) -> None:
    writing = gone_quiet(make_repo(cache, "org/writing", blobs=("f00d", "beef.1a2b.incomplete")))
    killed = gone_quiet(make_repo(cache, "org/killed", marked=True))  # api killed between files
    complete = gone_quiet(make_repo(cache, "org/complete"))

    HfModelFiles(cache)

    assert not writing.exists()
    assert not killed.exists()
    assert complete.exists()


def test_cleanup_keeps_a_download_still_being_written(cache: Path) -> None:
    preloading = make_repo(cache, "org/preloading", blobs=("beef.1a2b.incomplete",))  # Speaches

    HfModelFiles(cache)

    assert preloading.exists()


async def test_delete_removes_the_repo_folder(cache: Path) -> None:
    doomed = make_repo(cache, MODEL)
    kept = make_repo(cache, "org/other")
    files: ModelFiles = HfModelFiles(cache)

    await files.delete(MODEL)
    await files.delete(MODEL)  # already gone: nothing to do

    assert not doomed.exists()
    assert kept.exists()


async def test_a_delete_that_fails_says_why(cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_repo(cache, MODEL)
    files = HfModelFiles(cache)

    def refuse(path: object, *_args: object, **_kwargs: object) -> None:
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(shutil, "rmtree", refuse)

    with pytest.raises(SpeechSettingsError) as caught:
        await files.delete(MODEL)

    assert caught.value.status == 500
    assert caught.value.message == "Could not delete org/m: Permission denied"


async def test_a_worker_that_cannot_start_leaves_nothing(tmp_path: Path, cache: Path) -> None:
    files = hf_files(cache, [str(tmp_path / "no-such-worker")])

    with pytest.raises(FileNotFoundError):
        await files.download(MODEL)

    assert not (cache / REPO).exists()
    assert files.progress() is None


@pytest.mark.parametrize("model_id", ["..", "org/../..", "org\\..\\..", "org--x/y"])
async def test_a_model_id_cannot_name_another_folder(cache: Path, model_id: str) -> None:
    files = HfModelFiles(cache)

    with pytest.raises(ValueError, match=r"(?i)repo.?id"):
        await files.delete(model_id)


def test_worker_calls_snapshot_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    niceness: list[int] = []

    def snapshot_download(**kwargs: object) -> str:
        calls.append(kwargs)
        return str(tmp_path)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot_download)
    monkeypatch.setattr(os, "nice", niceness.append, raising=False)

    assert model_download.main([MODEL, str(tmp_path)]) == 0

    assert calls == [{"repo_id": MODEL, "cache_dir": tmp_path}]
    assert niceness == [10]


def test_worker_runs_where_there_is_no_nice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda **_kwargs: str(tmp_path))
    monkeypatch.delattr(os, "nice", raising=False)

    assert model_download.main([MODEL, str(tmp_path)]) == 0
