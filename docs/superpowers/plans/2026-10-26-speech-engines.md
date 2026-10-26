# Speech Engines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In Settings → Voice the learner chooses the speech recognition engine: Speaches (CPU, or NVIDIA) or whisper.cpp built with Vulkan (AMD and Intel GPUs). Each engine has its own model list, and a GPU engine that is down never breaks a conversation.

**Architecture:**
- A whisper.cpp adapter implements a new `GpuSpeechToText` port (`SpeechToText` plus `running()` and `load()`). Its models are single GGML files from `ggerganov/whisper.cpp`, kept in the same Hugging Face cache folder the api already manages.
- `HfModelFiles` learns single-file models (`<repo>/<file>` ids). `SpeechService` generalises its per-kind logic to three *tracks*:
  - recognition on Speaches;
  - recognition on whisper.cpp;
  - voice on Speaches.
- A conversation resolves its `Recognition` at `session.start` and loads the GPU model then. It switches to Speaches for good when the GPU server cannot be reached.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.1 + Alembic (SQLCipher), httpx2, `huggingface_hub` 2.2.0, pytest; React 19, TanStack Query + openapi-react-query, Radix (`radix-ui`), Vitest + Testing Library; Docker Compose, just.

**Spec:** `docs/superpowers/specs/2026-10-26-speech-engines-design.md`. Read it first: this plan argues from it and does not repeat its reasons.

**whisper.cpp facts:** read from its server source at commit `231638a` (identical at the pinned image's commit `0c7be69`), its Vulkan Dockerfile, and the Hugging Face API. Tasks 2 and 7 quote the ones they need.

## Global Constraints

- **Branch and commits:**
  - Work on `feat/speech-engines`. One PR into `develop` at the end; the controller opens it.
  - Commit after every task with `git -c user.name=GeneralErdon -c user.email=leandrofermin@gmail.com commit`, after `export PATH="$HOME/.cargo/bin:$PATH"` (the hooks need it).
  - Messages are Conventional Commits. Wrap the body at 72 columns, and no body line may start with `word: `.
  - Every message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
  - Never touch the global git config. Never push.
- **Coverage ≥ 97 %** for Python (`just test-py`) and the UI (`just test-ui`). Never lower a threshold.
- **Layering** (import-linter, `just check-py`):
  - `vt_api.domain` is pure, with no httpx2.
  - Only `container.py` imports `vt_api.adapters`.
  - `vt_contracts` imports no service.
- **Checks to run:**
  - `just check-py` and `just test-py`;
  - `just check-ui` and `just test-ui`;
  - `just types`, after any contract change, with the regenerated files committed.
- **Do NOT run any of these.** The maintainer is short on RAM, and only the maintainer downloads images and models.
  - `cargo`, `just test`, `just check`, `just desktop`, `just bundle`, `vite build`;
  - Docker builds, pulls or `up`;
  - anything that downloads a model.

  These are fine: `docker compose ... config --quiet`, `just -n <recipe>` and `sh -n`.
- **No new dependencies.** httpx2 and `huggingface_hub` 2.2.0 are already there.
- **UI text** is in English. Settings changes save at once.
- **Spec values to keep exactly:**
  - **Engines:**
    - The ids are `openai` and `whispercpp` (`VT_STT_BACKEND` is the default engine).
    - The UI labels are `Speaches · CPU` and `whisper.cpp · GPU`.
    - Messages name them "Speaches" and "whisper.cpp (GPU)".
  - **Default GPU model:** `ggerganov/whisper.cpp/ggml-small.en-q8_0.bin`.
  - **New variables:**
    - `VT_STT_GPU_BASE_URL`: default `http://stt-gpu:8080/v1` (Compose); `just dev-api` sets `http://localhost:8002/v1`.
    - `VT_STT_GPU_MODELS_ROOT`: default `/models`.
    - `VT_STT_GPU_MODEL`: default as above.
  - **The `stt-gpu` service:**
    - profiles `[gpu, amd]`;
    - port `127.0.0.1:8002:8080`;
    - `/dev/dri`;
    - image `ghcr.io/ggml-org/whisper.cpp:main-vulkan-0c7be696371069e0baa2515ed7aa08d5a5473aa6@sha256:4d25bb2f233afa2799642ffcb3e49dbb5586a3cbf7588f3ec7be727d9fa9acbd`. It was built on 2026-10-19 and is amd64 only.
  - **Start command:** `just voice gpu`.
- **Never print `.env` values** or secrets.

## Review Focus

1. **One GGML file removed, its siblings kept.** Uninstalling, a failed or cancelled download, or `cleanup()` of a stale partial must never delete the other GGML files in `models--ggerganov--whisper.cpp`. Tests: Task 1.
2. **The GPU server is down at the start, or dies mid-conversation.** The conversation goes on with Speaches and sends one `speech_engine_unavailable` warning, not one per turn. A read timeout or an HTTP error from a live server stays `stt_failed`. Tests: Task 2 (error classes) and Task 5.
3. **`/load` fails.** If the file does not load, the server process exits and the connection drops. The session falls back to Speaches, and the adapter forgets which model is loaded, so it loads again next time. Tests: Tasks 2 and 5.
4. **The saved engine is whisper.cpp, but the GPU engine is unusable now.** That means `VT_SPEECH_MODELS_DIR` is unset or the server is stopped. The settings view, the model lists, status and conversations still work on Speaches. Saving another field still succeeds: only a *changed* engine is checked. Tests: Tasks 3 and 5.
5. **The repository revision moved.** A GGML file downloaded under an older snapshot is still "installed", and its path is the snapshot that holds it. Tests: Task 1.

---

### Task 1: Single-file models in the models folder

**Files:**
- Modify: `services/api/src/vt_api/domain/speech.py`, adding `split_model_id`.
- Modify: `services/api/src/vt_api/adapters/model_download.py`.
- Modify: `services/api/src/vt_api/adapters/model_files.py`.
- Modify: `services/api/src/vt_api/ports/speech.py`, adding the `ModelFiles` methods below.
- Test:
  - `services/api/tests/unit/test_speech_domain.py`;
  - `services/api/tests/unit/test_model_files.py`;
  - `services/api/tests/unit/test_speech_service.py`, only to give `FakeFiles` the new methods so mypy accepts it as `ModelFiles`.

**Interfaces:**
- Produces:
  - **`split_model_id(model_id: str) -> tuple[str, str | None]`**
    - `"org/name"` gives `("org/name", None)`, and `"org/name/file.bin"` gives `("org/name", "file.bin")`.
    - It raises `ValueError` for more than three segments or an empty one.
  - **`ModelFiles.present(model_ids: Collection[str]) -> set[str]`** (async)
    - Returns the single-file ids among `model_ids` whose file is complete in the cache.
    - It never includes the file a download of ours is writing.
  - **`ModelFiles.snapshot_path(model_id: str) -> str | None`** (async)
    - Returns the complete file's POSIX path relative to the cache folder, e.g. `models--ggerganov--whisper.cpp/snapshots/<rev>/ggml-base.en.bin`, or `None`.
    - It prefers the snapshot that `refs/main` names, and otherwise takes any snapshot holding the file.
  - **`HfModelFiles(cache_dir, *, single_file_repos: Collection[str] = (), total_size=..., worker=..., poll_s=...)`**
    - `single_file_repos` names the repositories whose files are separate models (Task 3 passes `ggerganov/whisper.cpp`).
  - **The worker's argv is unchanged:** `<model_id> <cache_dir>`.
  - **The marker file `.voice-tutor-downloading` now holds the model id being downloaded.** An empty marker, written by an older api, still means the whole repository.

- [ ] **Step 1: Write the failing tests**

  Each test gets its comment with the exact facts below, and builds the cache layout by hand. The layout is a `refs/main` file, symlinks in `snapshots/<rev>/` pointing to `../../blobs/<etag>`, and blobs that end in `.incomplete` while partial.

  - `test_split_model_id`:
    - the two shapes above;
    - `ValueError` for `"a/b/c/d"` and `"a//b"`.
  - `test_worker_downloads_only_the_file`. Patch `huggingface_hub.snapshot_download`, and assert it was called with:
    - `repo_id="ggerganov/whisper.cpp"`;
    - `allow_patterns=["ggml-base.en.bin"]`;
    - `cache_dir=Path(<dir>)`.

    A two-segment id is called without `allow_patterns`.
  - `test_total_size_of_one_file_is_that_file`. `hub_total_size("ggerganov/whisper.cpp/ggml-base.en.bin")` sums only the sibling whose `rfilename == "ggml-base.en.bin"`. Patch `HfApi.model_info` to return siblings of 147964211 and 264477561 bytes, and expect 147964211.
  - `test_single_file_progress_counts_only_the_new_file`. The repository already holds a complete 1 000-byte sibling. The fake worker writes 300 bytes into a new `.incomplete` blob, so the progress reports `done_bytes == 300`.
  - `test_incomplete_names_the_file_being_downloaded`. While a single-file download runs, `incomplete() == {"ggerganov/whisper.cpp/ggml-base.en.bin"}`.
  - `test_present_and_snapshot_path`. The layout:
    - `refs/main` is `r2`;
    - `snapshots/r2/ggml-base.en.bin` points to blob `aaa`;
    - `snapshots/r1/ggml-small.en-q8_0.bin` points to blob `bbb`;
    - `snapshots/r2/ggml-medium.en-q5_0.bin` is a dangling link.

    The assertions:
    - `present({base, small, medium, "Systran/faster-whisper-tiny.en"}) == {base, small}`;
    - `snapshot_path(base)` ends in `snapshots/r2/ggml-base.en.bin`;
    - `snapshot_path(small)` ends in `snapshots/r1/ggml-small.en-q8_0.bin`;
    - `snapshot_path(medium) is None`.
  - `test_present_leaves_out_the_file_being_downloaded`. With the marker holding base's id, `present({base}) == set()` even though its link resolves.
  - `test_delete_one_file_keeps_its_siblings`:
    - `delete(base)` removes its links in every snapshot and blob `aaa`;
    - the small file's link and blob `bbb` stay;
    - deleting small then removes the whole `models--ggerganov--whisper.cpp` folder;
    - a blob still linked by another remaining entry is kept.
  - `test_failed_single_file_download_keeps_its_siblings`. The worker exits 1 after writing `ccc.incomplete`. Afterwards `ccc.incomplete` and the marker are gone, while base and small stay.
  - `test_cleanup_of_a_stale_single_file_download_keeps_siblings`. There is a marker naming medium, plus an orphan `ccc.incomplete` older than `STALE_AFTER_S`. After `cleanup()` the orphan and the marker are gone, while base and small stay.
  - `test_cleanup_without_a_marker_in_a_single_file_repo_keeps_siblings`. There is a stale orphan `.incomplete` and no marker. Only the orphan is removed.
  - Every existing whole-repository test keeps passing unchanged.

- [ ] **Step 2: Run them, and see them fail**

  Run: `uv run pytest services/api/tests/unit/test_model_files.py services/api/tests/unit/test_speech_domain.py -q`

  Expected: FAIL (missing names or behaviour).

- [ ] **Step 3: Implement**

  - **`split_model_id`** goes in the domain. The worker and `HfModelFiles` use it, and `_repo()` uses only the repository part.
  - **Single-file downloads:**
    - The marker's content is the model id.
    - Progress is the repository's bytes on disk minus the bytes there before the worker started, clamped as today.
  - **Cleanup in a repository listed in `single_file_repos`, or under a marker naming a file:**
    - remove the orphan `*.incomplete` blobs (those whose `<etag>` is not complete);
    - remove the dangling `snapshots/*/<file>` links and the marker;
    - remove the repository folder only when no snapshot file is left.

    The same single-file-aware removal runs when a download fails or is cancelled (`_discard`, and the failed-worker path). Every other repository keeps today's whole-folder removal.
  - **`delete()` of a single-file id** removes that file's links and the blobs that no remaining link uses, then the folder once it is empty of snapshot files.

- [ ] **Step 4: Run all Python checks**

  Run: `just check-py && just test-py`

  Expected: PASS, with coverage ≥ 97 %.

- [ ] **Step 5: Commit**: `feat(api): download and remove single model files`.

---

### Task 2: The whisper.cpp adapter

**Files:**
- Create: `services/api/src/vt_api/adapters/whispercpp.py`.
- Modify:
  - `services/api/src/vt_api/domain/speech.py`, adding `EngineUnreachable`;
  - `services/api/src/vt_api/ports/speech.py`, adding `GpuSpeechToText`.
- Test: `services/api/tests/unit/test_whispercpp.py`, using `httpx2.MockTransport` the way `test_speaches.py` does.

**Interfaces:**
- Produces:
  - **`class EngineUnreachable(ProviderError)`**, built with `EngineUnreachable(base_url: str)`. Its reason is `"connection"` and its message is `f"Could not connect to {base_url}."`.
  - **`class GpuSpeechToText(SpeechToText, Protocol)`**, adding:
    - `async def running(self) -> bool`. True when the health check answers 200 or 503. Never raises.
    - `async def load(self, model: str) -> None`.

    `model` is always the file's path **relative to the shared models folder** (from `ModelFiles.snapshot_path`), in `transcribe` too.
  - **`WhisperCppSpeechToText(http: httpx2.AsyncClient, base_url: str, models_root: str)`**, with these constants:
    - `CONNECT_TIMEOUT_S = 3.0`;
    - `HEALTH_TIMEOUT_S = 3.0`;
    - `LOAD_TIMEOUT_S = 120.0`.

**Server facts to code against.** `base` is `VT_STT_GPU_BASE_URL`, ending in `/v1`.
- **Health.** `GET {base}/health` answers 200 `{"status":"ok"}`, or 503 `{"status":"loading model"}` around a `/load`.
  - While the first model loads at startup, the port refuses connections.
  - After a `/load` that answered 400, health stays 503 until a later successful load.
- **Load.** `POST {base}/load` takes a multipart field `model` (send it as `files={"model": (None, path)}`) holding the path inside the container: `f"{models_root}/{model}"`.
  - Success is 200, plain text `Load was successful!`.
  - A missing file is 400 `{"error":"model not found!"}`.
  - A file that exists but does not load makes the **process exit**, so the connection drops.
  - Loads and inference share one mutex.
  - No route says which model is loaded.
- **Transcription.** `POST {base}/audio/transcriptions` takes multipart `file=("speech.wav", wav, "audio/wav")`, `response_format=json` and `language=en`.
  - The answer is `{"text": " Hello there.\n"}`, which the adapter strips.
  - Errors are 400 `{"error":"failed to read audio data"}`, 500 `{"error":"failed to process audio"}`, or a 500 in plain text.

- [ ] **Step 1: Write the failing tests**
  - `test_transcribe_posts_the_wav_and_strips_the_text`:
    - the request goes to `http://gpu:8080/v1/audio/transcriptions`;
    - its multipart has the `file`, `response_format` and `language` parts;
    - the result is `"Hello there."`.
  - `test_transcribe_loads_a_different_model_first`:
    - the first call to `transcribe(wav, "models--g--w/snapshots/r/a.bin", 30)` POSTs `/load` with `model == "/models/models--g--w/snapshots/r/a.bin"`, then transcribes;
    - a second call with the same model does not load again;
    - a call with another model loads it.
  - `test_load_is_skipped_when_already_loaded`, and `test_concurrent_loads_are_serialised`. Two `load()` calls with different models run one after the other: the fake records non-overlapping requests.
  - `test_failed_load_forgets_the_loaded_model`. After a 400, and after a dropped connection (`httpx2.RemoteProtocolError` from the transport), the next `load` of the same model POSTs again. A 400 raises a `ProviderError` with the server's `error` text in its message.
  - `test_connection_refused_is_engine_unreachable`. When the transport raises `httpx2.ConnectError` on transcribe or load, the adapter raises `EngineUnreachable`. Same for `httpx2.ConnectTimeout`.
  - `test_read_timeout_and_http_errors_are_not_unreachable`:
    - `httpx2.ReadTimeout` raises a `ProviderError` that is **not** an `EngineUnreachable` (`timed_out`);
    - so does a 500 with `{"error": "failed to process audio"}`;
    - the transcription timeout is the `timeout_s` passed in, and the connect timeout is `CONNECT_TIMEOUT_S`.
  - `test_running`: 200 gives True, 503 gives True, and `ConnectError` gives False.
  - `test_status`:
    - 200 gives `reachable=True, model_ready=True`;
    - 503 gives `reachable=True, model_ready=False`, with detail `"whisper.cpp is loading a model."`;
    - a refused connection gives `reachable=False`, with detail `"Could not connect to http://gpu:8080/v1."`;
    - `base_url` is `http://gpu:8080/v1`, and `model` is echoed.

- [ ] **Step 2: Run them, and see them fail**

  Run: `uv run pytest services/api/tests/unit/test_whispercpp.py -q`

  Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

  - Use `httpx2` directly, not the openai SDK: only the transport tells a refused connection from a read timeout.
  - Map errors with `provider_errors`:
    - an HTTP error answer goes to `from_status`;
    - a read timeout goes to `timed_out`;
    - any other `httpx2.HTTPError` goes to `connection_failed`.
  - One `asyncio.Lock` covers each load-then-transcribe, and each `load()`.
  - The loaded model is forgotten on any failed load, and on `EngineUnreachable`.

- [ ] **Step 4: Run all Python checks**

  Run: `just check-py && just test-py`

  Expected: PASS.

- [ ] **Step 5: Commit**: `feat(api): whisper.cpp speech recognition adapter`.

---

### Task 3: The engine and the GPU model in the saved settings, and the GPU catalog

**Files:**
- Modify:
  - `packages/contracts/src/vt_contracts/speech.py`;
  - `services/api/src/vt_api/domain/speech.py`;
  - `services/api/src/vt_api/config.py`;
  - `services/api/src/vt_api/container.py`;
  - `services/api/src/vt_api/services/speech.py`;
  - `services/api/src/vt_api/adapters/sql/tables.py`;
  - `services/api/src/vt_api/adapters/sql/speech_settings.py`.
- Create: `services/api/src/vt_api/adapters/sql/migrations/versions/v0003_speech_engine.py`.
- Regenerate with `just types`: `apps/desktop/openapi.json` and `apps/desktop/src/generated/`.
- Modify, only so the UI still type-checks and passes:
  - `apps/desktop/src/test/fake-api.ts`, adding the new fields to the fixtures;
  - `apps/desktop/src/features/settings/voice-settings.tsx`, where `latest()` carries the two new fields. No new UI behaviour.
- Test:
  - `test_speech_domain.py`, `test_config.py`, `test_sql_storage.py`;
  - `test_speech_service.py`;
  - `tests/integration/test_speech_api.py`;
  - `services/api/tests/conftest.py`, where `speech_defaults` gains the fields.

**Interfaces:**
- Consumes: Task 1 (`present`, `single_file_repos`) and Task 2 (`GpuSpeechToText`, `WhisperCppSpeechToText`).
- Produces:
  - **Contracts:**
    - `type SttEngine = Literal["openai", "whispercpp"]`.
    - `SpeechSettings` gains required fields `stt_engine: SttEngine` and `stt_gpu_model: str`, right after `stt_model`.
    - `SpeechModel` gains `engine: SttEngine`. Voice models are `"openai"`.
    - `class SpeechEngineState(BaseModel)`, frozen with `extra="forbid"`, has fields `engine: SttEngine`, `running: bool` and `manageable: bool`.
    - `SpeechModels` gains `engines: list[SpeechEngineState]`, in the order openai, then whispercpp.
  - **Domain:**
    - `DEFAULT_GPU_MODEL = "ggerganov/whisper.cpp/ggml-small.en-q8_0.bin"`.
    - `CatalogEntry` gains `engine: SttEngine = "openai"`, as its last field.
    - `catalog(kind: SpeechKind, default_model_id: str, engine: SttEngine = "openai") -> list[CatalogEntry]` filters by kind and engine. A configured default that is not in the catalog is appended with that engine.
    - `single_file_repos(gpu_default: str) -> frozenset[str]`: the repositories of the whispercpp entries, plus `gpu_default`'s.
  - **Config:**
    - `stt_backend: SttEngine = "openai"` (it was `SttBackend`; drop that alias);
    - `stt_gpu_base_url: HttpUrl = HttpUrl("http://stt-gpu:8080/v1")`;
    - `stt_gpu_models_root: str = Field(default="/models", pattern=r"^/")`;
    - `stt_gpu_model: str = Field(default=DEFAULT_GPU_MODEL, pattern=r"^[^/]+/[^/]+/[^/]+$")`.
  - **`SpeechService(..., gpu_stt: GpuSpeechToText | None = None)`**
    - **Tracks:** `type _Track = tuple[SpeechKind, SttEngine]`, with `_TRACKS = (("recognition", "openai"), ("recognition", "whispercpp"), ("voice", "openai"))`.
    - **Which model a track uses:** `_model(settings, track)` reads `stt_model`, `stt_gpu_model` or `tts_model`.
    - **The GPU engine is usable** when `gpu_stt` and `files` are both set.

**The GPU catalog.** Keys and labels as below. `english_only` is true for the first three, and `approx_mb` comes from the Hugging Face sizes.

| key | file in `ggerganov/whisper.cpp` | label | hint | MB |
|---|---|---|---|---|
| `whispercpp-base-en` | `ggml-base.en.bin` | Whisper base (English) | Fastest, least accurate | 148 |
| `whispercpp-small-en-q8` | `ggml-small.en-q8_0.bin` | Whisper small (English, 8-bit) | Fast and accurate on a GPU | 264 |
| `whispercpp-medium-en-q5` | `ggml-medium.en-q5_0.bin` | Whisper medium (English, 5-bit) | More accurate | 539 |
| `whispercpp-large-v3-turbo-q5` | `ggml-large-v3-turbo-q5_0.bin` | Whisper large v3 turbo (5-bit) | The accurate choice (multilingual) | 574 |
| `whispercpp-large-v3-turbo-q8` | `ggml-large-v3-turbo-q8_0.bin` | Whisper large v3 turbo (8-bit) | Most accurate; more GPU memory (multilingual) | 874 |
| `whispercpp-large-v3-turbo` | `ggml-large-v3-turbo.bin` | Whisper large v3 turbo (full) | Full precision; the most GPU memory (multilingual) | 1625 |

- [ ] **Step 1: Write the failing tests**
  - **Domain.**
    - `catalog("recognition", SMALL_Q8, "whispercpp")` returns the six GPU entries in that order, all with `engine == "whispercpp"`.
    - `catalog("recognition", WHISPER)` keeps today's eight entries.
    - `single_file_repos(DEFAULT_GPU_MODEL) == {"ggerganov/whisper.cpp"}`.
  - **Config.**
    - The three defaults above.
    - `VT_STT_GPU_MODEL=ggml-small.bin` is rejected at startup.
    - `VT_STT_GPU_MODELS_ROOT=models` is rejected.
  - **Storage.**
    - `test_the_migrations_match_the_tables` passes.
    - A row saved before v0003 reads back with `stt_engine == "openai"` and `stt_gpu_model == DEFAULT_GPU_MODEL`. Use the migration's server defaults; the downgrade drops both columns.
    - A saved `stt_engine="whispercpp"` round-trips.
  - **Service.** The fixtures gain:
    - a `FakeGpu` whose `running()` returns its `up` attribute, with `load`, `transcribe` and `status`;
    - a `FakeFiles.present` backed by the same `models` set.
  - **Service: `models()` and saving.**
    - `models()` lists the GPU rows with `engine="whispercpp"`. They are `installed` when present in the files, and `selected` matches `stt_gpu_model`.
    - `engines` is `[{"openai", running=True, manageable=True}, {"whispercpp", running=<FakeGpu.up>, manageable=True}]`.
    - Without `files`, whispercpp is `manageable=False`.
    - Without `gpu_stt`, it is `running=False`.
    - `test_switching_to_a_stopped_engine_is_refused`: saving `stt_engine="whispercpp"` while the GPU is not running gives 409, with the message ``whisper.cpp (GPU) is not running: start it with `just voice gpu` (Linux, AMD or Intel GPU).``
    - Without `files`, the message is `whisper.cpp (GPU) needs VT_SPEECH_MODELS_DIR, the models folder it shares with the api (see docs/configuration.md).`
    - Switching back to `openai` while Speaches does not answer gives 409 with ``Speaches is not running: start it with `just voice`.``
    - `test_switching_to_a_running_engine_saves`.
    - `test_a_gpu_model_must_be_installed`:
      - choosing the medium GPU model while it is not present gives 422 `... is not installed: download it first.`;
      - a Speaches id as `stt_gpu_model` gives 422 `... is not a speech recognition model for whisper.cpp.`;
      - the default GPU model is always accepted.
    - `test_only_a_changed_engine_is_checked`: with the saved engine whisper.cpp and the GPU stopped, saving a new `tts_speed` succeeds.
  - **Integration (`test_speech_api.py`).**
    - `GET /v1/speech/models` includes `engines` and the GPU rows.
    - `PUT /v1/speech/settings` with a stopped GPU engine gives 409.

- [ ] **Step 2: Run them, and see them fail**

  Run: `uv run pytest services/api/tests -q -x`

  Expected: FAIL.

- [ ] **Step 3: Implement**

  - **Migration `v0003`** (revision `"0003"`, revises `"0002"`) adds two columns:
    - `stt_engine`, `String(20)`, NOT NULL, `server_default="openai"`;
    - `stt_gpu_model`, `String(200)`, NOT NULL, `server_default="ggerganov/whisper.cpp/ggml-small.en-q8_0.bin"`.

    The downgrade drops them through `batch_alter_table`.
  - **Container:**
    - Build `WhisperCppSpeechToText(speaches_http, str(settings.stt_gpu_base_url), settings.stt_gpu_models_root)`.
    - Pass `single_file_repos=single_file_repos(settings.stt_gpu_model)` to `HfModelFiles`.
    - The defaults gain `stt_engine=settings.stt_backend` and `stt_gpu_model=settings.stt_gpu_model`.
  - **Service: generalise the per-kind helpers to tracks.**
    - The helpers are `_model`, `_default`, `_catalog`, `_installed`, `_check_installed` and `_kind_models` (rename it `_track_models`).
    - `save()` checks each track whose model changed. Then, only if `stt_engine` changed, it checks that the new engine runs.
    - Speaches "runs" when the recognition server's `installed()` does not raise.
    - The GPU track's installed set is `files.present(<the track's catalog ids>)`, less the running download, or empty without `files`.
    - `_session()` and `for_session()` keep today's behaviour here; Task 5 changes them.
  - **UI.** Run `just types`, then make `just check-ui` and `just test-ui` pass with only the fixture and `latest()` changes.

- [ ] **Step 4: Run every check**

  Run: `just check-py && just test-py && just types && just check-ui && just test-ui`

  Expected: PASS. The regenerated files are committed.

- [ ] **Step 5: Commit**: `feat(api): save the speech recognition engine and its GPU model`.

---

### Task 4: GPU models: download, cancel, uninstall, use

**Files:**
- Modify: `services/api/src/vt_api/services/speech.py`.
- Test: `services/api/tests/unit/test_speech_service.py` and `services/api/tests/integration/test_speech_api.py`.

**Interfaces:**
- Consumes: the tracks and the GPU catalog from Task 3, and `ModelFiles.present` and `download`/`delete` of single-file ids from Task 1.
- Produces: no new names. `download`, `cancel_download`, `uninstall` and `_select` work for GPU keys.

- [ ] **Step 1: Write the failing tests**
  - `test_download_a_gpu_model_and_use_it`:
    - `download("whispercpp-medium-en-q5", activate=True)` downloads `ggerganov/whisper.cpp/ggml-medium.en-q5_0.bin` through `files`;
    - its row is `downloading` meanwhile;
    - once `files` finishes, `stt_gpu_model` is that id, and `stt_model` is unchanged;
    - **there is no Speaches "does it see it" check** for GPU models: the GPU server never lists them.
  - `test_gpu_download_without_activate_leaves_the_choice`.
  - `test_cancel_a_gpu_download`.
  - `test_gpu_models_need_the_models_folder`. Without `files`, a GPU download gives 409 with the message `Models for whisper.cpp (GPU) can be downloaded and uninstalled only with VT_SPEECH_MODELS_DIR set (see docs/configuration.md).`
  - `test_uninstall_a_gpu_model`:
    - it calls `files.delete(<id>)`;
    - it does **not** call `unload` on any Speaches server;
    - the default GPU model gives 409 (`... is the default and stays installed.`);
    - the selected GPU model gives 409 (`... is in use: choose another model first.`);
    - the downloading one gives 409, as for Speaches.
  - `test_choosing_a_speaches_model_does_not_touch_the_gpu_choice`, and the reverse.
  - **Integration.** `POST /v1/speech/models/whispercpp-base-en/download` returns 202, and the row is `downloading`. `DELETE /v1/speech/models/whispercpp-base-en` on the selected model returns 409.

- [ ] **Step 2: Run them, and see them fail**

  Run: `uv run pytest services/api/tests -q -x -k "gpu"`

  Expected: FAIL.

- [ ] **Step 3: Implement** in `SpeechService`:
  - `_files_for(track)`: the Speaches tracks keep today's rule. The GPU track gets `files` when the GPU engine is usable, and it does not need the GPU server to be running.
  - `_run` skips the server-lists-it check for the GPU track.
  - `uninstall` skips `unload` for the GPU track.
  - `_select` sets `stt_gpu_model` for GPU entries.
  - `_unmanageable(track)` gets the message above for the GPU track, and keeps today's for the others.

- [ ] **Step 4: Run all Python checks**

  Run: `just check-py && just test-py`

  Expected: PASS.

- [ ] **Step 5: Commit**: `feat(api): download and uninstall GPU speech models`.

---

### Task 5: Conversations use the chosen engine

**Files:**
- Modify:
  - `services/api/src/vt_api/domain/speech.py`;
  - `services/api/src/vt_api/services/speech.py`;
  - `services/api/src/vt_api/realtime/session.py`;
  - `packages/contracts/src/vt_contracts/speech.py`;
  - `packages/contracts/src/vt_contracts/ws.py`.
- Regenerate with `just types`, and update the UI fixtures (`fake-api.ts`) for `recognition_engine` only.
- Test: `test_speech_service.py`, `test_session.py`, `tests/integration/test_ws_api.py` and `test_speech_api.py`.

**Interfaces:**
- Consumes: Tasks 1–3 (`snapshot_path`, `present`, `GpuSpeechToText`, `EngineUnreachable`, tracks).
- Produces:
  - **`Recognition`**: `@dataclass(frozen=True, slots=True) class Recognition`, with fields:
    - `engine: SttEngine`;
    - `model: str`, the catalog id, which measured speed and warnings name;
    - `server_model: str`. On Speaches it is the model id; on whisper.cpp, the `snapshot_path`.
  - **`SessionSpeech(recognition: Recognition, voice: VoiceChoice, max_turn_s: int, missing: tuple[SpeechKind, ...] = (), fallback: Recognition | None = None, engine_unavailable: SttEngine | None = None)`**. It replaces `stt_model`.
  - **Service methods:**
    - `SpeechService.for_session()` resolves the speech choice and loads the GPU model.
    - `view()` and `status()` resolve it without loading.
    - `SpeechService.transcribe(wav: bytes, audio_s: float, recognition: Recognition) -> str`. It uses `gpu_stt` for `whispercpp` and `stt` otherwise. Measured speed is keyed by `recognition.model`.
  - **Contracts:**
    - `SpeechStatus` gains `recognition_engine: SttEngine`.
    - `ErrorCode` gains `"speech_engine_unavailable"`.

**Resolution (`_session(settings, *, load: bool)`).**
- `speaches = Recognition("openai", m, m)`, where `m` is the installed `stt_model` or the Speaches default, as today.
- If `stt_engine == "whispercpp"`, the GPU engine is usable, and `gpu_stt.running()`:
  - Pick the GPU model: the saved `stt_gpu_model` if present, else the GPU default if present, else none.
  - If there is a GPU model and its `snapshot_path`, and `load` is set, call `gpu_stt.load(path)`. A `ProviderError` there counts as unavailable.
  - Then recognition is `Recognition("whispercpp", id, path)`, and `fallback = speaches`.
- Otherwise, with `stt_engine == "whispercpp"`: recognition is `speaches`, and `engine_unavailable = "whispercpp"`.
- `missing` contains `"recognition"` when the recognition model in use differs from the saved model *of the engine in use*.

**Messages (exact).**
- At the start, when `engine_unavailable`, the warning is ``whisper.cpp (GPU) is not running: Speaches transcribes this conversation. Start it with `just voice gpu`, or choose Speaches in Settings → Voice.``
- The first time a turn hits `EngineUnreachable`, the session:
  - switches to `fallback` for the rest of the conversation;
  - sends `whisper.cpp (GPU) stopped answering: Speaches transcribes the rest of this conversation.`;
  - transcribes that same turn with Speaches.

Both use `speech_engine_unavailable`, with `retryable=True`.

- [ ] **Step 1: Write the failing tests**
  - **Service.**
    - `test_session_uses_the_gpu_and_loads_its_model`:
      - with `stt_engine="whispercpp"`, the GPU running and small present, `for_session().recognition == Recognition("whispercpp", SMALL_Q8, <path>)`;
      - `FakeGpu.load` was called with that path;
      - `fallback` is Speaches.
    - `test_view_and_status_do_not_load`.
    - `test_session_falls_back_when_the_gpu_is_stopped`: the GPU is not running, so recognition is Speaches with `engine_unavailable == "whispercpp"`.
    - Same when `load` raises `ProviderError`, and when the GPU engine is unusable (no `files`).
    - `test_missing_gpu_model_uses_the_gpu_default`: the saved medium is absent but small is present, so recognition is small with `missing == ("recognition",)`.
    - `test_transcribe_with_the_gpu_records_its_speed`.
    - `test_status_reports_the_engine_in_use`: `recognition_engine` is `"whispercpp"` when the GPU is used, and `"openai"` when it fell back.
  - **Session.**
    - `test_start_warns_when_the_engine_is_unavailable`: the exact message above.
    - `test_gpu_unreachable_mid_conversation_switches_to_speaches_once`:
      - the first voice turn raises `EngineUnreachable` from the GPU, so it is transcribed by Speaches;
      - one `speech_engine_unavailable` warning is sent;
      - the second turn goes straight to Speaches, with no second warning.
    - Two voice turns failing concurrently still send one warning.
    - `test_gpu_read_timeout_is_stt_failed`: a plain `ProviderError` from the GPU gives `stt_failed` and no fallback.
    - Existing tests move from `SessionSpeech(stt_model=...)` to `Recognition`.
  - **Integration.** A WebSocket session against a stopped GPU engine gets the start warning.

- [ ] **Step 2: Run them, and see them fail**

  Run: `uv run pytest services/api/tests -q -x`

  Expected: FAIL.

- [ ] **Step 3: Implement** as specified above. The session keeps `self._recognition` from `_start`. The check-and-switch on `EngineUnreachable` has no `await` between the check and the assignment, so concurrent turns warn once.

- [ ] **Step 4: Run every check**

  Run: `just check-py && just test-py && just types && just check-ui && just test-ui`

  Expected: PASS.

- [ ] **Step 5: Commit**: `feat(api): conversations use the chosen speech engine, with fallback`.

---

### Task 6: Settings → Voice: the engine choice and the GPU models

**Files:**
- Create:
  - `apps/desktop/src/features/settings/engine-choice.tsx`;
  - `apps/desktop/src/features/settings/engine-choice.test.tsx`.
- Modify:
  - `voice-settings.tsx`;
  - `speech-models.tsx`;
  - `speech-section.tsx`, all in `apps/desktop/src/features/settings/`;
  - `apps/desktop/src/test/fake-api.ts`.
- Test:
  - `voice-settings.test.tsx`;
  - `speech-section.test.tsx`;
  - `apps/desktop/src/features/practice/practice-voice.test.tsx`.

**Interfaces:**
- Consumes: `Schemas['SttEngine']`, `Schemas['SpeechEngineState']`, `SpeechModel.engine`, `SpeechStatus.recognition_engine` and `SpeechSettings.stt_engine | stt_gpu_model`.
- Produces:
  - **`EngineChoice({ engines, value, disabled, onChange })`**:
    - a Radix `RadioGroup` styled as a two-segment control, with `aria-label="Speech recognition engine"`;
    - a stopped engine's item is disabled;
    - each item shows a hint.
  - **`ModelList` gains an optional `engine?: SttEngine` prop.** With it, recognition rows are filtered by `model.engine`.

**Copy (exact).**
- `Speaches · CPU`, with the hint ``Uses an NVIDIA GPU with the `nvidia` profile``.
- `whisper.cpp · GPU`:
  - while running, its hint is `AMD and Intel GPUs, through Vulkan`;
  - while stopped, it is ``Start it with `just voice gpu` (Linux, AMD or Intel GPU)``.
- When the saved engine is stopped, an alert says `whisper.cpp (GPU) is not running: Speaches is used meanwhile.`
- In the readiness row:
  - the label is `Speech recognition · whisper.cpp (GPU)` when `recognition_engine === 'whispercpp'`;
  - the setup command shown is `just voice gpu` in that case, and `just voice` otherwise.

- [ ] **Step 1: Write the failing tests**
  - `engine-choice.test.tsx`:
    - both options are rendered;
    - the stopped one is disabled and shows its start hint;
    - choosing the other calls `onChange('whispercpp')`.
  - `voice-settings.test.tsx`:
    - switching the engine PUTs the settings with `stt_engine: 'whispercpp'` and the other fields unchanged;
    - under whisper.cpp the list shows only GPU rows;
    - **Use** on a GPU row PUTs `stt_gpu_model` and leaves `stt_model` as it was;
    - the alert appears when the saved engine is stopped;
    - the turn-length estimate uses the selected model of the engine in use.
  - `speech-section.test.tsx`: the readiness label and the command for `recognition_engine: 'whispercpp'`.
  - `practice-voice.test.tsx`: a `speech_engine_unavailable` error shows its message in the alert, and does **not** end the "transcribing" state. It is not in `SPEECH_ERRORS`, and stays out of it.

- [ ] **Step 2: Run them, and see them fail**

  Run: `pnpm --filter @voice-tutor/desktop test -- --run src/features/settings src/features/practice`

  Expected: FAIL.

- [ ] **Step 3: Implement.** In `VoiceSettings`:
  - `EngineChoice` sits above the recognition `ModelList`, which gets `engine={view.stt_engine}`.
  - `manageable` for whisper.cpp comes from `engines`.
  - `chooseModel` sets `stt_gpu_model` for `engine === 'whispercpp'` rows.

- [ ] **Step 4: Run the UI checks**

  Run: `just check-ui && just test-ui`

  Expected: PASS, with coverage ≥ 97 %.

- [ ] **Step 5: Commit**: `feat(ui): choose the speech recognition engine in Settings → Voice`.

---

### Task 7: Compose, `just voice gpu`, and the docs

**Files:**
- Modify:
  - `compose.yaml`;
  - `justfile`;
  - `.env.example`, if it lists the STT variables;
  - `docs/configuration.md`, `docs/hardware.md`, `docs/architecture.md` and `docs/roadmap.md`;
  - `README.md`, in its voice section.
- Create: `docker/stt-gpu/start.sh`.

**Interfaces:**
- Consumes: the variables and defaults from Task 3.
- Produces:
  - **The Compose services `stt-gpu-model` (one-shot) and `stt-gpu`.**
  - **`just voice [gpu]`.**

**Facts.**
- The whisper.cpp image has no ENTRYPOINT. Its CMD is `/bin/bash`, and its WorkingDir is `/app`.
- `whisper-server` is on PATH at `/usr/local/bin/whisper-server`.
- The runtime has `curl`, `ffmpeg`, `mesa-vulkan-drivers` (RADV and ANV) and `libvulkan1`.
- `--host` defaults to 127.0.0.1, so pass `--host 0.0.0.0`.
- The first model loads before the port opens.
- No model is in the image.

**Steps:**

- [ ] **Step 1: Write `docker/stt-gpu/start.sh`** (POSIX sh, `set -eu`).
  - Read `VT_STT_GPU_MODEL`, with the default above.
  - Split it into the repository and the file. Build `/models/models--<org>--<name>`, and read `refs/main`.
  - Then `exec whisper-server --host 0.0.0.0 --port 8080 --request-path /v1 --inference-path /audio/transcriptions -m <dir>/snapshots/<rev>/<file>`.
  - It must fail with a clear message on stderr when the file is missing.

  Check it with `sh -n docker/stt-gpu/start.sh`.
- [ ] **Step 2: Add the services to `compose.yaml`**, replacing the `TODO(Phase 1)` comment after `stt-nvidia`.
  - **`stt-gpu-model` is a one-shot service:**
    - image `ghcr.io/speaches-ai/speaches:0.9.0-rc.3-cpu`, the same one `stt-cpu` uses and already pulled;
    - profiles `[gpu, amd]`;
    - `entrypoint: ["python", "-c", "<hf_hub_download of the repo and file split from $MODEL>"]`;
    - `environment: { MODEL: ${VT_STT_GPU_MODEL:-ggerganov/whisper.cpp/ggml-small.en-q8_0.bin}, HF_HUB_DISABLE_XET: "1" }`;
    - the same `./data/models:/home/ubuntu/.cache/huggingface/hub` volume as Speaches;
    - `restart: "no"`.

    **Verify first,** by reading speaches' Dockerfile at tag `v0.9.0-rc.3` on GitHub (do not pull), that `python` on the image's PATH has `huggingface_hub`. If it does not, use the venv's python path.
  - **`stt-gpu`:**
    - the pinned image;
    - profiles `[gpu, amd]`;
    - `entrypoint: ["/bin/sh", "/opt/voice-tutor/start.sh"]`;
    - `VT_STT_GPU_MODEL` passed through, with the same default;
    - devices `/dev/dri:/dev/dri`;
    - ports `127.0.0.1:8002:8080`;
    - volumes `./data/models:/models:ro` and `./docker/stt-gpu/start.sh:/opt/voice-tutor/start.sh:ro`;
    - `depends_on: { stt-gpu-model: { condition: service_completed_successfully } }`;
    - the healthcheck uses `*model-healthcheck` with `["CMD", "curl", "-fsS", "http://127.0.0.1:8080/v1/health"]`;
    - `restart: unless-stopped`. It restarts with the default model after a failed `/load`.
  - **`api`** gets `depends_on: stt-gpu: { condition: service_started, required: false }`.
  - **Comments** in the house style: what each service is, Linux only, and the `GGML_NATIVE` caveat in one line. The image's CPU code may be built for its CI machine. If the container dies with "Illegal instruction", see `docs/hardware.md`.

  Check: `docker compose --profile "*" config --quiet` passes, and `docker compose --profile amd config --services` lists `stt-gpu` and `stt-gpu-model`.
- [ ] **Step 3: Update the justfile.**
  - `voice engine=""`. `just voice gpu` adds `--profile gpu` and the `stt-gpu` service to the `up -d --wait` command.
    - Any other value is an `error(...)` naming the usage `just voice [gpu]`.
    - The echo line names what starts.
    - The recipe comment says the GPU engine is Linux only, for AMD or Intel GPUs.
  - `dev-api` gains `[env("VT_STT_GPU_BASE_URL", "http://localhost:8002/v1")]`.

  Check: `just -n voice gpu` and `just -n voice` print the expected commands, and `just -n voice foo` fails with the usage.
- [ ] **Step 4: Update the docs.** Each section is short, in the house style.
  - **`configuration.md`:**
    - `VT_STT_BACKEND` becomes "default speech recognition engine until one is saved in Settings → Voice";
    - the three new variables;
    - a "GPU speech recognition (whisper.cpp)" subsection under the voice setup.
  - **`hardware.md`:**
    - the `amd` row points to `stt-gpu`, whisper.cpp with Vulkan;
    - a section on using the RX 9060 XT (`just up amd`, or `VT_PROFILE=amd`) and the Arc iGPU (`just voice gpu` with `VT_PROFILE=cpu`);
    - Linux only;
    - the illegal-instruction caveat and what to do: report it, and try the previous tag `main-vulkan-7e26d3b0d5bced6c8217ef09710ec2f969001241`.
  - **`architecture.md`:**
    - the `stt` component row mentions both engines;
    - a new row in "Architecture decisions": "Speech recognition engines: Speaches and whisper.cpp (Vulkan) behind one port; the api switches between running servers and never manages containers", why, and the alternative rejected (the api driving Docker through its socket, which is root on the host). Phase 4 runs the same engine natively.
  - **`roadmap.md`:** under the Phase 0 latency item, one line saying to compare CPU and GPU with the turn metrics.
  - **`README.md`:** the voice section names `just voice gpu`.
- [ ] **Step 5: Run the checks**

  Run: `uv run pre-commit run --all-files`, `docker compose --profile "*" config --quiet`, `just check-py`, and `just check-ui` (for prettier on Markdown, if it runs there).

  Expected: PASS.
- [ ] **Step 6: Commit**: `feat: start whisper.cpp on the GPU with just voice gpu`.

---

## After the tasks (controller)

1. The final whole-branch review, as subagent-driven development prescribes.
2. Push, and open the PR into `develop`. Its body carries the maintainer's manual test plan:
   - `just voice gpu` on the laptop (Arc 140V, `VT_PROFILE=cpu`, Ollama Cloud) and `just up amd` on the desktop (RX 9060 XT);
   - pick the engine;
   - compare the `heard` times on CPU and on GPU;
   - switch GGML models, and download, cancel and uninstall one;
   - `docker compose stop stt-gpu` mid-session, and check the single warning and the fallback;
   - watch for "Illegal instruction" in `docker compose logs stt-gpu`.
3. Run a PR review of the changes (`/code-review` on the PR), fix what it finds, and wait for **CI ok**.
