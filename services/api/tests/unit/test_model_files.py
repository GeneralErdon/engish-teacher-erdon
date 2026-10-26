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
from huggingface_hub import HfApi

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
repo = Path(cache_dir) / ("models--" + "--".join(model_id.split("/")[:2]))
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
        os.utime(path, (then, then), follow_symlinks=False)
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


def test_cleanup_keeps_a_complete_repo_with_a_stray_incomplete(cache: Path) -> None:
    # huggingface_hub names each attempt's temporary file uniquely: a killed attempt leaves
    # one behind, beside the blob a later attempt finished.
    stray = gone_quiet(make_repo(cache, "org/stray", blobs=("f00d", "f00d.1a2b3c4d.incomplete")))

    HfModelFiles(cache)

    assert stray.exists()


def test_cleanup_keeps_a_download_still_being_written(cache: Path) -> None:
    preloading = make_repo(cache, "org/preloading", blobs=("beef.1a2b.incomplete",))  # Speaches

    HfModelFiles(cache)

    assert preloading.exists()


async def test_incomplete_names_half_written_models_however_recent(cache: Path) -> None:
    """A quick restart after a hard kill: `cleanup()` keeps these folders for now, and the
    server may list them, but they are not installed."""
    make_repo(cache, "org/writing", blobs=("f00d", "beef.1a2b.incomplete"))
    make_repo(cache, "org/killed", marked=True)
    make_repo(cache, "org/complete")
    make_repo(cache, "org/stray", blobs=("f00d", "f00d.1a2b3c4d.incomplete"))
    files: ModelFiles = HfModelFiles(cache)

    assert await files.incomplete() == {"org/writing", "org/killed"}


async def test_downloading_again_completes_a_killed_download(tmp_path: Path, cache: Path) -> None:
    make_repo(cache, MODEL, blobs=(), marked=True)
    files = hf_files(cache, fake_worker(tmp_path))
    assert await files.incomplete() == {MODEL}

    await files.download(MODEL)

    assert await files.incomplete() == set()
    assert (cache / REPO / "blobs" / "f00d").stat().st_size == TOTAL


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

    # a two-segment id fetches the whole repository: no `allow_patterns`
    assert calls == [{"repo_id": MODEL, "cache_dir": tmp_path}]
    assert niceness == [10]


def test_worker_runs_where_there_is_no_nice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda **_kwargs: str(tmp_path))
    monkeypatch.delattr(os, "nice", raising=False)

    assert model_download.main([MODEL, str(tmp_path)]) == 0


GGML = "ggerganov/whisper.cpp"
GGML_REPO = "models--ggerganov--whisper.cpp"
BASE = f"{GGML}/ggml-base.en.bin"
SMALL = f"{GGML}/ggml-small.en-q8_0.bin"
MEDIUM = f"{GGML}/ggml-medium.en-q5_0.bin"


def ggml_files(cache: Path, worker: Sequence[str] = ()) -> HfModelFiles:
    return HfModelFiles(
        cache,
        single_file_repos={GGML},
        total_size=sized(300),
        worker=worker,
        poll_s=0.01,
    )


def link(repo: Path, revision: str, file: str, etag: str | None) -> None:
    """`snapshots/<revision>/<file>` -> `../../blobs/<etag>`, as `huggingface_hub` writes it; the
    blob is 10 bytes, and absent for `None` (a dangling link)."""
    snapshot = repo / "snapshots" / revision
    snapshot.mkdir(parents=True, exist_ok=True)
    target = f"../../blobs/{etag or 'missing'}"
    (snapshot / file).symlink_to(target)
    if etag is not None:
        (repo / "blobs").mkdir(exist_ok=True)
        (repo / "blobs" / etag).write_bytes(b"x" * 10)


def ggml_repo(cache: Path, *, files: Sequence[tuple[str, str, str | None]]) -> Path:
    repo = cache / GGML_REPO
    (repo / "refs").mkdir(parents=True)
    (repo / "refs" / "main").write_text("r2")
    for revision, file, etag in files:
        link(repo, revision, file, etag)
    return repo


BASE_AND_SMALL = [("r2", "ggml-base.en.bin", "aaa"), ("r1", "ggml-small.en-q8_0.bin", "bbb")]


def test_worker_downloads_only_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # One repository, many independent files: `allow_patterns` keeps the worker to the one.
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda **kw: calls.append(kw))
    monkeypatch.setattr(os, "nice", lambda _increment: 0, raising=False)

    assert model_download.main([BASE, str(tmp_path)]) == 0

    assert calls == [
        {"repo_id": GGML, "allow_patterns": ["ggml-base.en.bin"], "cache_dir": tmp_path}
    ]


async def test_total_size_of_one_file_is_that_file(monkeypatch: pytest.MonkeyPatch) -> None:
    # ggml-base.en.bin is 147964211 bytes and ggml-small.en-q8_0.bin 264477561.
    siblings = [
        SimpleNamespace(rfilename="ggml-base.en.bin", size=147964211),
        SimpleNamespace(rfilename="ggml-small.en-q8_0.bin", size=264477561),
    ]
    monkeypatch.setattr(HfApi, "model_info", lambda *_a, **_k: SimpleNamespace(siblings=siblings))

    assert await model_files.hub_total_size(BASE) == 147964211
    assert await model_files.hub_total_size(GGML) == 147964211 + 264477561


@pytest.mark.parametrize("size", [0, None])
async def test_total_size_of_a_listed_empty_file_is_zero(
    monkeypatch: pytest.MonkeyPatch, size: int | None
) -> None:
    siblings = [SimpleNamespace(rfilename="ggml-base.en.bin", size=size)]
    monkeypatch.setattr(HfApi, "model_info", lambda *_a, **_k: SimpleNamespace(siblings=siblings))

    assert await model_files.hub_total_size(BASE) == 0


async def test_a_file_hugging_face_does_not_have_is_not_downloaded(
    tmp_path: Path, cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker would fetch nothing and succeed, and the model would be activated without
    its file: refuse before it starts."""
    siblings = [SimpleNamespace(rfilename="ggml-base.en.bin", size=147964211)]
    monkeypatch.setattr(HfApi, "model_info", lambda *_a, **_k: SimpleNamespace(siblings=siblings))
    files = HfModelFiles(
        cache,
        single_file_repos={GGML},
        total_size=model_files.hub_total_size,
        worker=[str(tmp_path / "no-such-worker")],  # started, it would raise FileNotFoundError
    )

    with pytest.raises(SpeechSettingsError) as caught:
        await files.download(MEDIUM)

    assert caught.value.status == 502
    assert caught.value.message == (
        "Hugging Face has no file ggml-medium.en-q5_0.bin in ggerganov/whisper.cpp."
    )
    assert not (cache / GGML_REPO).exists()
    assert files.progress() is None


async def test_single_file_progress_counts_only_the_new_file(tmp_path: Path, cache: Path) -> None:
    # The repository holds a complete 1 000-byte sibling; the worker writes 300 bytes into a
    # new `.incomplete` blob (the fake worker writes `f00d.1a2b3c4d.incomplete`).
    repo = ggml_repo(cache, files=[("r2", "ggml-small.en-q8_0.bin", "bbb")])
    (repo / "blobs" / "bbb").write_bytes(b"x" * 1000)
    files = ggml_files(cache, fake_worker(tmp_path, steps=3))
    download = asyncio.create_task(files.download(BASE))
    seen: list[int] = []
    while not download.done():
        if (current := files.progress()) is not None:
            seen.append(current[1].done_bytes)
        await asyncio.sleep(0.005)
    await download

    assert max(seen) == 300
    assert (repo / "blobs" / "bbb").stat().st_size == 1000


async def test_incomplete_names_the_file_being_downloaded(tmp_path: Path, cache: Path) -> None:
    # The marker holds the model id while the worker runs.
    ggml_repo(cache, files=BASE_AND_SMALL[1:])
    files = ggml_files(cache, fake_worker(tmp_path, steps=10, pause=0.05))
    download = asyncio.create_task(files.download(BASE))
    await until_bytes_on_disk(files)

    assert await files.incomplete() == {BASE}
    assert (cache / GGML_REPO / DOWNLOADING_MARKER).read_text() == BASE

    await download
    assert await files.incomplete() == set()


async def test_an_empty_marker_still_means_the_whole_repository(cache: Path) -> None:
    # Written by an older api.
    make_repo(cache, MODEL, marked=True)

    assert await HfModelFiles(cache, single_file_repos={GGML}).incomplete() == {MODEL}


async def test_present_and_snapshot_path(cache: Path) -> None:
    # refs/main is r2; base is linked in r2, small only in the older r1; medium's link dangles.
    ggml_repo(cache, files=[*BASE_AND_SMALL, ("r2", "ggml-medium.en-q5_0.bin", None)])
    files: ModelFiles = ggml_files(cache)

    assert await files.present({BASE, SMALL, MEDIUM, "Systran/faster-whisper-tiny.en"}) == {
        BASE,
        SMALL,
    }
    assert str(await files.snapshot_path(BASE)).endswith(
        f"{GGML_REPO}/snapshots/r2/ggml-base.en.bin"
    )
    assert str(await files.snapshot_path(SMALL)).endswith(
        f"{GGML_REPO}/snapshots/r1/ggml-small.en-q8_0.bin"
    )
    assert await files.snapshot_path(MEDIUM) is None
    assert await files.snapshot_path("Systran/faster-whisper-tiny.en") is None
    assert await files.snapshot_path(f"{GGML}/ggml-none.bin") is None
    assert await files.snapshot_path("other/repo/file.bin") is None


async def test_snapshot_path_is_relative_to_the_cache_and_prefers_refs_main(cache: Path) -> None:
    ggml_repo(cache, files=[("r1", "ggml-base.en.bin", "aaa"), ("r2", "ggml-base.en.bin", "aaa")])
    files = ggml_files(cache)

    assert await files.snapshot_path(BASE) == f"{GGML_REPO}/snapshots/r2/ggml-base.en.bin"


async def test_present_leaves_out_the_file_being_downloaded(cache: Path) -> None:
    repo = ggml_repo(cache, files=BASE_AND_SMALL)
    (repo / DOWNLOADING_MARKER).write_text(BASE)
    files = ggml_files(cache)

    assert await files.present({BASE}) == set()  # its link resolves, yet it is being replaced
    assert await files.present({BASE, SMALL}) == {SMALL}


async def test_delete_one_file_keeps_its_siblings(cache: Path) -> None:
    repo = ggml_repo(
        cache, files=[*BASE_AND_SMALL, ("r1", "ggml-base.en.bin", "aaa"), ("r3", "x.bin", "aaa")]
    )
    files: ModelFiles = ggml_files(cache)

    await files.delete(BASE)

    # The link of "x.bin" (another model) still uses blob aaa, so the blob stays.
    assert not (repo / "snapshots" / "r2" / "ggml-base.en.bin").is_symlink()
    assert not (repo / "snapshots" / "r1" / "ggml-base.en.bin").is_symlink()
    assert (repo / "blobs" / "aaa").exists()
    await files.delete(f"{GGML}/x.bin")
    assert not (repo / "blobs" / "aaa").exists()
    assert (repo / "snapshots" / "r1" / "ggml-small.en-q8_0.bin").exists()
    assert (repo / "blobs" / "bbb").exists()

    await files.delete(SMALL)

    assert not repo.exists()


async def test_deleting_the_last_file_spares_a_download_into_the_folder(cache: Path) -> None:
    """Medium is downloading into the folder, and has no link yet: removing base, the only
    complete file, must not remove the folder under it."""
    repo = ggml_repo(cache, files=[("r2", "ggml-base.en.bin", "aaa")])
    (repo / "blobs" / "ccc.1a2b3c4d.incomplete").write_bytes(b"x")
    (repo / DOWNLOADING_MARKER).write_text(MEDIUM)
    files: ModelFiles = ggml_files(cache)

    await files.delete(BASE)

    assert not (repo / "snapshots" / "r2" / "ggml-base.en.bin").is_symlink()
    assert not (repo / "blobs" / "aaa").exists()
    assert (repo / DOWNLOADING_MARKER).read_text() == MEDIUM
    assert (repo / "blobs" / "ccc.1a2b3c4d.incomplete").exists()


async def test_a_delete_of_a_file_that_is_not_there_is_fine(cache: Path) -> None:
    await ggml_files(cache).delete(BASE)


async def test_failed_single_file_download_keeps_its_siblings(tmp_path: Path, cache: Path) -> None:
    # The worker exits 1 after writing `f00d.1a2b3c4d.incomplete`.
    repo = ggml_repo(cache, files=BASE_AND_SMALL)
    files = ggml_files(cache, fake_worker(tmp_path, mode="fail"))

    with pytest.raises(SpeechSettingsError):
        await files.download(MEDIUM)

    assert not list((repo / "blobs").glob("*.incomplete"))
    assert not (repo / DOWNLOADING_MARKER).exists()
    assert await files.present({BASE, SMALL}) == {BASE, SMALL}


async def test_a_failed_first_file_download_leaves_no_folder(tmp_path: Path, cache: Path) -> None:
    files = ggml_files(cache, fake_worker(tmp_path, mode="fail"))

    with pytest.raises(SpeechSettingsError):
        await files.download(BASE)

    assert not (cache / GGML_REPO).exists()


async def test_a_cancelled_single_file_download_keeps_its_siblings(
    tmp_path: Path, cache: Path
) -> None:
    repo = ggml_repo(cache, files=BASE_AND_SMALL)
    files = ggml_files(cache, fake_worker(tmp_path, steps=100, pause=0.05))
    download = asyncio.create_task(files.download(MEDIUM))
    await until_bytes_on_disk(files)

    await files.cancel()
    with pytest.raises(asyncio.CancelledError):
        await download

    assert not list((repo / "blobs").glob("*.incomplete"))
    assert await files.present({BASE, SMALL}) == {BASE, SMALL}


def test_cleanup_of_a_stale_single_file_download_keeps_siblings(cache: Path) -> None:
    # A marker naming medium and an orphan `ccc.incomplete`, older than STALE_AFTER_S.
    repo = ggml_repo(cache, files=[*BASE_AND_SMALL, ("r2", "ggml-medium.en-q5_0.bin", None)])
    (repo / "blobs" / "ccc.1a2b3c4d.incomplete").write_bytes(b"x")
    (repo / DOWNLOADING_MARKER).write_text(MEDIUM)
    gone_quiet(repo)

    HfModelFiles(cache)

    assert not (repo / "blobs" / "ccc.1a2b3c4d.incomplete").exists()
    assert not (repo / DOWNLOADING_MARKER).exists()
    assert not (repo / "snapshots" / "r2" / "ggml-medium.en-q5_0.bin").is_symlink()
    assert (repo / "snapshots" / "r2" / "ggml-base.en.bin").exists()
    assert (repo / "snapshots" / "r1" / "ggml-small.en-q8_0.bin").exists()


def test_cleanup_without_a_marker_in_a_single_file_repo_keeps_siblings(cache: Path) -> None:
    repo = ggml_repo(cache, files=BASE_AND_SMALL)
    (repo / "blobs" / "ccc.incomplete").write_bytes(b"x")  # older huggingface_hub naming
    gone_quiet(repo)

    HfModelFiles(cache, single_file_repos={GGML})

    assert not (repo / "blobs" / "ccc.incomplete").exists()
    assert (repo / "snapshots" / "r2" / "ggml-base.en.bin").exists()
    assert (repo / "snapshots" / "r1" / "ggml-small.en-q8_0.bin").exists()


def test_cleanup_removes_a_single_file_repo_with_nothing_complete(cache: Path) -> None:
    repo = ggml_repo(cache, files=[])
    (repo / "blobs").mkdir()
    (repo / "blobs" / "ccc.1a2b.incomplete").write_bytes(b"x")
    gone_quiet(repo)

    HfModelFiles(cache, single_file_repos={GGML})

    assert not repo.exists()
