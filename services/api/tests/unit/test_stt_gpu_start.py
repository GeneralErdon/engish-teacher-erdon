"""`docker/stt-gpu/start.sh`, which finds the GPU server's startup model in the shared models
folder, run with `sh` against a temporary folder: `MODELS_ROOT` stands for the mounted `/models`,
and `WHISPER_SERVER=echo` prints the server's command line instead of starting it."""

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[4] / "docker" / "stt-gpu" / "start.sh"
MODEL = "ggerganov/whisper.cpp/ggml-base.en.bin"
FILE = "ggml-base.en.bin"
REPO = "models--ggerganov--whisper.cpp"
SERVER_FLAGS = (
    "--host 0.0.0.0 --port 8080 --request-path /v1 --inference-path /audio/transcriptions"
)


def _start(models: Path) -> subprocess.CompletedProcess[str]:
    environment = {
        "PATH": os.environ["PATH"],
        "MODELS_ROOT": str(models),
        "WHISPER_SERVER": "echo",
        "VT_STT_GPU_MODEL": MODEL,
    }
    return subprocess.run(  # noqa: S603 (our own script, with fixed arguments)
        ["/bin/sh", str(SCRIPT)], env=environment, capture_output=True, text=True, check=False
    )


def _fetched(models: Path, revision: str, *files: str) -> str:
    """Files downloaded under `revision`, as the Hugging Face cache keeps them: links to blobs.
    Returns the snapshot folder."""
    repo = models / REPO
    snapshot = repo / "snapshots" / revision
    snapshot.mkdir(parents=True)
    (repo / "blobs").mkdir(exist_ok=True)
    for file in files:
        (repo / "blobs" / f"{revision}-{file}").write_bytes(b"ggml")
        (snapshot / file).symlink_to(f"../../blobs/{revision}-{file}")
    return str(snapshot)


def _main(models: Path, revision: str) -> None:
    refs = models / REPO / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(revision)


def test_starts_on_the_file_of_the_main_revision(tmp_path: Path) -> None:
    _fetched(tmp_path, "aaaa", FILE)  # an older revision that also has it
    snapshot = _fetched(tmp_path, "bbbb", FILE)
    _main(tmp_path, "bbbb")

    started = _start(tmp_path)

    assert (started.returncode, started.stderr) == (0, "")
    assert started.stdout == f"{SERVER_FLAGS} -m {snapshot}/{FILE}\n"


def test_finds_the_file_after_the_revision_moved(tmp_path: Path) -> None:
    """A later download (another GGML file) moved `refs/main` to a revision this file was never
    fetched under: a restart must still find it, or the container restarts forever."""
    snapshot = _fetched(tmp_path, "aaaa", FILE)
    _fetched(tmp_path, "bbbb", "ggml-medium.en-q5_0.bin")
    _main(tmp_path, "bbbb")

    started = _start(tmp_path)

    assert (started.returncode, started.stderr) == (0, "")
    assert started.stdout == f"{SERVER_FLAGS} -m {snapshot}/{FILE}\n"


def test_a_file_in_no_snapshot_is_not_downloaded(tmp_path: Path) -> None:
    _fetched(tmp_path, "bbbb", "ggml-medium.en-q5_0.bin")
    _main(tmp_path, "bbbb")

    started = _start(tmp_path)

    assert (started.returncode, started.stdout) == (1, "")
    assert started.stderr == (
        f"stt-gpu: {FILE} is in no snapshot of {tmp_path}/{REPO}: the model {MODEL} is not "
        "downloaded\n"
    )


def test_no_repository_folder_asks_about_the_mount(tmp_path: Path) -> None:
    started = _start(tmp_path)

    assert (started.returncode, started.stdout) == (1, "")
    assert started.stderr == (
        f"stt-gpu: {tmp_path}/{REPO} not found: the model {MODEL} is not downloaded (is "
        "./data/models mounted?)\n"
    )
