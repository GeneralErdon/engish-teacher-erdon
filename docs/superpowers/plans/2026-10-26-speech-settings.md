# Speech Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In Settings → Voice the learner can choose:
- the speech recognition model;
- the tutor's voice model, voice and speed;
- the longest turn.

Models are downloaded (with progress and cancel) and uninstalled by the api. Everything is saved in the encrypted database.

**Architecture:**
- A `SpeechService` (the `LearnerService` pattern) owns the saved choices, the curated catalog, downloads with an "activate when done" intent, measured transcription speed, and the choice each conversation uses.
- Two new ports:
  - `SpeechModelServer`: the Speaches HTTP API (installed models, registry voices, unload).
  - `ModelFiles`: downloads into the Hugging Face cache folder that Speaches reads, run in a child process so they can be cancelled.
- The STT/TTS adapters take the model, voice and speed per call. The conversation session reads the choice at `session.start` and cuts turns over the limit instead of dropping them.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.1 + Alembic (SQLCipher), `huggingface_hub` 2.2.0, httpx2, pytest; React 19, TanStack Query + openapi-react-query, shadcn/ui, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-23-speech-settings-design.md`. Read it first: this plan argues from it and does not repeat its reasons.

## Global Constraints

- **Branch and commits:**
  - One branch, `feat/speech-settings`, and one PR into `develop` at the end.
  - Commit after every task with `git -c user.name=GeneralErdon -c user.email=leandrofermin@gmail.com commit`.
  - Messages are Conventional Commits, with the body wrapped at 72 columns, and no body line may start with `word: `.
  - Every message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- **Coverage ≥ 97 %** for Python (`just test-py`) and the UI (`just test-ui`). Never lower a threshold.
- **Layering** (import-linter, `just check-py`):
  - `vt_api.domain` is pure.
  - Only `container.py` imports `vt_api.adapters`.
  - `vt_contracts` imports no service.
- **Checks to run:** `just check-py`, `just test-py`, `just check-ui`, `just test-ui`, `just types`.
- **Do NOT run** `cargo`, `just test`, `just check`, `just desktop`, `just bundle`, `vite build`, Docker builds, or anything that downloads a model. The maintainer is short on RAM, and the maintainer downloads models.
- **New dependency:** `huggingface-hub` **2.2.0** in `services/api/pyproject.toml`. 2.3.0 is under 7 days old.
  - `uv.lock` must change only by adding `huggingface-hub` and the packages it brings.
  - Every added package must be ≥ 7 days old on PyPI. Check before committing.
- **UI text** is in English. Settings changes save at once (like `LearningSection`).
- **Spec values to keep exactly:**
  - Turn length is 30–300 s, default `VT_MAX_TURN_S=120`, with options `30 s · 1 min · 2 min · 3 min · 5 min`.
  - Speed is 0.7–1.3, default `VT_TTS_SPEED` 0.95.
  - Default models are `Systran/faster-distil-whisper-small.en` and `speaches-ai/Kokoro-82M-v1.0-ONNX`.
  - Piper models are requested at `sample_rate=24000`.
  - One download at a time.
- **Never print `.env` values** or secrets.

## Review Focus

1. **The download finishes but Speaches does not list the model** (folder not shared). The learner sees a clear error naming `VT_SPEECH_MODELS_DIR`, the activation intent is dropped, and the saved choice does not change. *(Task 6)*
2. **The api restarted mid-download:** a half-written repo folder must not show as installed, or Speaches tries to load it. Leftover partial folders are removed when `ModelFiles` starts. *(Task 4)*
3. **Switching the voice model to one that lacks the current voice** (Kokoro `af_heart` → Piper) picks the new model's first English voice instead of saving an invalid pair. *(Task 6)*
4. **A turn longer than the limit** is cut at exactly `max_turn_s`. It is transcribed with `cut=True`, and the measured speed uses the cut length. *(Task 8)*
5. **Clicking Download twice, or Uninstall on the model being downloaded:**
   - The same model again only updates the activate intent (no 409).
   - A different model gets a 409.
   - Uninstalling the downloading model gets a 409 asking to cancel first.
   *(Task 6)*

---

### Task 1: Speech contracts, configuration and the curated catalog

**Files:**
- Modify: `packages/contracts/src/vt_contracts/speech.py`
- Modify: `services/api/src/vt_api/config.py`
- Create: `services/api/src/vt_api/domain/speech.py`
- Test: `services/api/tests/unit/test_speech_domain.py`, `services/api/tests/unit/test_config.py`

**Interfaces:**
- Produces (in `vt_contracts.speech`; all models `frozen=True, extra="forbid"`; the existing `ModelStatus` and `SpeechStatus` stay):
  ```python
  type SpeechKind = Literal["recognition", "voice"]
  type ModelState = Literal["installed", "downloading", "available"]


  class SpeechSettings(BaseModel):  # body of PUT /v1/speech/settings
      stt_model: str  # Hugging Face id, e.g. "Systran/faster-distil-whisper-small.en"
      tts_model: str
      tts_voice: str
      tts_speed: float = Field(ge=0.7, le=1.3)
      max_turn_s: int = Field(ge=30, le=300)


  class SpeechSettingsView(SpeechSettings):
      source: Literal["environment", "saved"]
      missing: list[SpeechKind] = []  # saved model not installed: the default is used
      pending: list[str] = []  # model ids that become active when their download ends


  class DownloadProgress(BaseModel):
      done_bytes: int
      total_bytes: int | None


  class SpeechModel(BaseModel):
      key: str  # catalog slug, used in URLs
      kind: SpeechKind
      model_id: str
      label: str
      hint: str
      approx_mb: int
      english_only: bool
      state: ModelState
      download: DownloadProgress | None
      default: bool
      selected: bool
      from_configuration: bool  # the env default is not in the curated list
      ms_per_audio_s: float | None  # measured transcription speed (recognition only)


  class SpeechModels(BaseModel):  # GET /v1/speech/models
      models: list[SpeechModel]
      recognition_manageable: bool
      voice_manageable: bool
      last_error: str | None  # the last failed download, until the next one starts


  class Voice(BaseModel):
      id: str
      name: str
      accent: Literal["american", "british"] | None
      gender: Literal["female", "male"] | None


  class DownloadRequest(BaseModel):
      activate: bool = False


  class VoicePreview(BaseModel):
      model: str
      voice: str
      speed: float = Field(ge=0.7, le=1.3)
  ```
- Produces (in `vt_api.domain.speech`, pure):
  ```python
  @dataclass(frozen=True, slots=True)
  class CatalogEntry:
      key: str; kind: SpeechKind; model_id: str; label: str; hint: str
      approx_mb: int; english_only: bool; sample_rate_hz: int | None = None   # set only for Piper

  @dataclass(frozen=True, slots=True)
  class VoiceChoice:
      model: str; voice: str; speed: float; sample_rate_hz: int | None = None

  @dataclass(frozen=True, slots=True)
  class SessionSpeech:                      # what one conversation uses
      stt_model: str; voice: VoiceChoice; max_turn_s: int; missing: tuple[SpeechKind, ...] = ()

  CATALOG: tuple[CatalogEntry, ...]
  def catalog(kind: SpeechKind, default_model_id: str) -> list[CatalogEntry]
  def entry(key: str) -> CatalogEntry | None
  def entry_for(model_id: str) -> CatalogEntry | None
  def transcription_timeout_s(audio_s: float) -> float     # 30 + 3 × audio_s
  class SpeechSettingsError(Exception):                     # .status: int (404|409|422|507), .message: str
  ```
- Produces (in `Settings`):
  - `speech_models_dir: Path | None = None`
  - `max_turn_s: int = Field(default=120, ge=30, le=300)`
  - `tts_speed` bounds become `ge=0.7, le=1.3`

- [ ] **Step 1: Write the failing tests**
  - `test_catalog_lists_the_curated_models_in_order`:
    - `[e.key for e in catalog("recognition", DEFAULT_STT)]` is the 8 recognition slugs in the spec's order: `whisper-tiny-en, whisper-base-en, distil-whisper-small-en, whisper-small-en, distil-whisper-medium-en, whisper-medium-en, distil-whisper-large-v3, whisper-large-v3-turbo`.
    - The voice list is `kokoro, kokoro-int8, piper-lessac, piper-ryan, piper-alba, piper-alan`, with the spec's Hugging Face ids.
  - `test_piper_entries_ask_for_the_output_rate`: every `piper-*` entry has `sample_rate_hz == 24000`; Kokoro has `None`.
  - `test_an_unknown_default_is_added_from_configuration`: `catalog("recognition", "acme/whisper-x")` ends with an entry whose `model_id == "acme/whisper-x"`, and whose key is unique, starting with `configured-`.
  - `test_transcription_timeout_grows_with_the_audio`: `transcription_timeout_s(10) == 60`, and `transcription_timeout_s(300) == 930`.
  - `test_config.py`:
    - `VT_MAX_TURN_S=20` and `VT_TTS_SPEED=1.5` are rejected.
    - `VT_SPEECH_MODELS_DIR=data/models` gives `Path("data/models")`.
    - The defaults are `None` and `120`.

- [ ] **Step 2: Run them and see them fail.** `uv run pytest services/api/tests/unit/test_speech_domain.py services/api/tests/unit/test_config.py -q` fails: there is no module `vt_api.domain.speech`, and the settings have no such fields.

- [ ] **Step 3: Implement the contracts, the settings fields and `vt_api.domain.speech`.**
  - Labels and hints come from the spec's tables. Key the catalog by slug.
  - Before filling in `approx_mb`, read the sizes from the Hugging Face API: `curl -s https://huggingface.co/api/models/<id>?blobs=true`, summing `siblings[].size`. This is metadata only, not a model download. Store whole MB.
  - `SpeechSettingsError` carries an HTTP status, so the routes stay thin.

- [ ] **Step 4: Run the tests and `just check-py`.** Both pass.

- [ ] **Step 5: Commit**: `feat(api): speech contracts, settings and model catalog`.

---

### Task 2: Saved speech settings (table, migration, repository)

**Files:**
- Modify: `services/api/src/vt_api/adapters/sql/tables.py`, `services/api/src/vt_api/ports/speech.py`
- Create: `services/api/src/vt_api/adapters/sql/migrations/versions/v0002_speech_settings.py`, `services/api/src/vt_api/adapters/sql/speech_settings.py`
- Test: `services/api/tests/unit/test_sql_storage.py`

**Interfaces:**
- Consumes: `SpeechSettings` (Task 1).
- Produces:
  - The port `SpeechSettingsRepository(Protocol)`: `async load() -> SpeechSettings | None` and `async save(settings: SpeechSettings) -> None`.
  - The adapter `SqlSpeechSettingsRepository(database: Database)`.
  - The table `speech_settings`, a single row with the `id = 1` check, with these columns:
    - `stt_model String(200)`, `tts_model String(200)`, `tts_voice String(100)`;
    - `tts_speed Float`, `max_turn_s Integer`;
    - `updated_at`.

- [ ] **Step 1: Write the failing tests**
  - `test_speech_settings_round_trip`: `load()` is `None` before anything is saved, and returns exactly what was saved afterwards.
  - `test_unreadable_speech_settings_fall_back`: a row written with SQL holding `max_turn_s = 5` loads as `None`, and logs a warning.
  - The existing tests `test_the_migrations_match_the_tables` and `test_migrations_go_down_and_up_again` must cover `v0002` with no changes to them.

- [ ] **Step 2: Run** `uv run pytest services/api/tests/unit/test_sql_storage.py -q` and see the new tests fail.

- [ ] **Step 3: Implement** the row, the migration (revision `"0002"`, down revision `"0001"`) and the repository. Mirror `SqlLearnerProfileRepository`: `anyio.to_thread`, validate with Pydantic, return `None` on a `ValidationError`.

- [ ] **Step 4: Run** the storage tests and `just check-py`. Both pass.

- [ ] **Step 5: Commit**: `feat(api): store the speech settings`.

---

### Task 3: The Speaches model server adapter

**Files:**
- Modify: `services/api/src/vt_api/ports/speech.py`
- Create: `services/api/src/vt_api/adapters/speaches.py`
- Test: `services/api/tests/unit/test_speaches.py`

**Interfaces:**
- Consumes: `Voice` (Task 1), and `ProviderError` from `vt_api.domain.llm`.
- Produces the port `SpeechModelServer(Protocol)`:
  - `async is_speaches() -> bool`: `GET {root}/v1/registry` answers 200 with `data`. Never raises.
  - `async installed() -> set[str]`: the ids from `GET /v1/models`. Raises `ProviderError` when unreachable.
  - `async voices(model_id: str) -> list[Voice]`: the English voices of that model from the cached `GET /v1/registry?task=text-to-speech`.
    - `language` maps `en-us` → `american` and `en-gb` → `british`; other languages are dropped.
    - `gender` is kept as given.
    - An empty list for unknown models.
  - `async unload(model_id: str) -> None`: `DELETE /api/ps/{model_id}`. A 404 is fine, because the model was not loaded.
- The adapter is `SpeachesServer(http: httpx2.AsyncClient, base_url: str)`. `base_url` is the configured `/v1` URL; strip the trailing `/v1` to get the root. The registry response is cached per instance after the first success.

- [ ] **Step 1: Write the failing tests** against `httpx2.MockTransport`, as `test_openai_tts.py` does.
  - `test_installed_lists_local_model_ids`.
  - `test_unreachable_server_raises_provider_error`.
  - `test_voices_are_english_with_accent_and_gender`, using a registry fixture with an `en-us` female, an `en-gb` male and a `ja` voice. Expect 2 voices.
  - `test_registry_is_fetched_once`: two `voices()` calls make one request.
  - `test_is_speaches_false_for_other_servers`: the registry returns 404.
  - `test_unload_ignores_not_loaded`: a 404 does not raise.

- [ ] **Step 2: Run** `uv run pytest services/api/tests/unit/test_speaches.py -q` and see them fail.

- [ ] **Step 3: Implement** `SpeachesServer`. Wrap `httpx2` errors in `ProviderError`, with the URL and a learner-readable message, as `provider_error` does for the SDK.

- [ ] **Step 4: Run** the tests and `just check-py`. Both pass.

- [ ] **Step 5: Commit**: `feat(api): read models and voices from Speaches`.

---

### Task 4: Model files: download in a child process, progress, cancel, delete

**Files:**
- Modify: `services/api/src/vt_api/ports/speech.py`, `services/api/pyproject.toml`, `uv.lock`
- Create: `services/api/src/vt_api/adapters/model_files.py`, `services/api/src/vt_api/adapters/model_download.py`
- Test: `services/api/tests/unit/test_model_files.py`

**Interfaces:**
- Consumes: `SpeechSettingsError` and `DownloadProgress` (Task 1).
- Produces the port `ModelFiles(Protocol)`:
  - `def progress() -> tuple[str, DownloadProgress] | None`: the model being downloaded and its bytes.
  - `async download(model_id: str) -> None`:
    - It returns once the files are complete.
    - It raises `SpeechSettingsError(507, …)` before starting if the disk lacks `total × 1.1` free.
    - It raises `SpeechSettingsError(502, …)` if the child fails.
    - It raises `asyncio.CancelledError` when cancelled.
  - `async cancel() -> None`: terminate the child and remove the partial repo folder.
  - `async delete(model_id: str) -> None`: remove `models--{org}--{name}`.
  - `def cleanup() -> None`: remove leftover partial repo folders. Call it from the constructor.
- The adapter is:
  ```python
  HfModelFiles(
      cache_dir: Path,
      *,
      total_size: Callable[[str], Awaitable[int]] = <HfApi().model_info(files_metadata=True), summing sibling sizes>,
      worker: Sequence[str] = (sys.executable, "-m", "vt_api.adapters.model_download"),
      poll_s: float = 0.5,
  )
  ```
- The worker `model_download.py` takes `main(argv: list[str]) -> int`. Its arguments are `<model_id> <cache_dir>`. It calls `os.nice(10)` when available, then `snapshot_download(repo_id, cache_dir=cache_dir)`. It runs with `HF_HUB_DISABLE_XET=1` set by the parent.
- **Progress** is the size of every file under `cache_dir/models--{org}--{name}/blobs` (`.incomplete` included) against `total_size`.
- **Partial** means the repo folder has an `*.incomplete` blob, or no `refs/main`.

- [ ] **Step 1: Add the dependency.** Run `uv add --package vt-api "huggingface-hub>=2.2.0"`, then make sure the lock resolved **2.2.0**; if not, `uv lock --upgrade-package huggingface-hub==2.2.0`.
  - `git diff uv.lock` must only add packages.
  - Check each added package's upload date on `https://pypi.org/pypi/<name>/json` (≥ 7 days).
  - Read the installed `huggingface_hub` source to confirm that `HF_HUB_DISABLE_XET` exists and that plain HTTP downloads write `blobs/*.incomplete`. If either is false, stop and report to the controller before going on.

- [ ] **Step 2: Write the failing tests.** Use a fake worker: a tiny Python script written to `tmp_path`, which creates the HF layout and writes N bytes in steps, sleeping between them. Inject `total_size` as a constant.
  - `test_progress_counts_bytes_on_disk`: while the download runs, `progress()` moves forward and stays ≤ total. When `download()` returns, `progress()` is `None`.
  - `test_cancel_stops_the_worker_and_removes_partial_files`: after `cancel()`, the task raises `CancelledError`, the child is gone, and the repo folder no longer exists.
  - `test_refuses_when_the_disk_is_too_small`: monkeypatch `shutil.disk_usage` to report 100 free against a 1000 total. The result is `SpeechSettingsError` with `status == 507`, and the message names both sizes in MB.
  - `test_a_failing_worker_is_an_error`: a worker that exits 1 gives `status == 502`.
  - `test_cleanup_removes_half_written_repos`: a folder with `blobs/x.incomplete` is removed, and a complete one (`refs/main` and blobs, no `.incomplete`) is kept.
  - `test_delete_removes_the_repo_folder`.
  - `test_worker_calls_snapshot_download` (worker module): monkeypatch `huggingface_hub.snapshot_download`, then `main(["org/m", str(tmp_path)])` returns `0`, with `repo_id="org/m"` and `cache_dir=tmp_path`.

- [ ] **Step 3: Run** `uv run pytest services/api/tests/unit/test_model_files.py -q` and see them fail.

- [ ] **Step 4: Implement** `HfModelFiles` and the worker, using `asyncio.create_subprocess_exec`. Read the poll loop's bytes in a thread with `anyio.to_thread`; it is file I/O.

- [ ] **Step 5: Run** the tests and `just check-py`. Both pass.

- [ ] **Step 6: Commit**: `feat(api): download speech models with progress and cancel`.

---

### Task 5: STT and TTS adapters take the model per call

**Files:**
- Modify:
  - `services/api/src/vt_api/ports/speech.py`, `services/api/src/vt_api/adapters/openai_stt.py`, `services/api/src/vt_api/adapters/openai_tts.py`
  - `services/api/src/vt_api/realtime/session.py`, `services/api/src/vt_api/http/ws.py`, `services/api/src/vt_api/container.py`
- Test: `services/api/tests/unit/test_openai_stt.py`, `services/api/tests/unit/test_openai_tts.py`, `services/api/tests/unit/test_session.py`, `services/api/tests/integration/*.py`

**Interfaces:**
- Consumes: `VoiceChoice` (Task 1).
- Produces:
  - `SpeechToText.transcribe(wav: bytes, model: str, timeout_s: float) -> str`
  - `SpeechToText.status(model: str) -> ModelStatus`
  - `TextToSpeech.synthesize(text: str, voice: VoiceChoice) -> AsyncIterator[bytes]`
  - `TextToSpeech.status(model: str) -> ModelStatus`
  - The constructors become `OpenAISpeechToText(client)` and `OpenAITextToSpeech(client)`.
  - Temporarily, until Task 8:
    - `ConversationSession(..., speech: SessionSpeech)` takes the choice the container builds from `Settings`, and calls the adapters with it, using `transcription_timeout_s(audio_s)`.
    - `Container` gains `session_speech: SessionSpeech`, and `/v1/speech/status` passes the configured models.
  - Everything stays green after this task.

- [ ] **Step 1: Update the tests first.**
  - Existing tests pass the model and voice per call.
  - New: `test_sends_the_per_call_timeout`. The request is made with the given timeout; assert it via the SDK's `timeout=` reaching the transport, or the request extension the SDK sets.
  - New: `test_piper_asks_for_24k`. With `VoiceChoice(..., sample_rate_hz=24000)`, the JSON body has `"sample_rate": 24000`. Without it, the key is absent.

- [ ] **Step 2: Run** both test files and see them fail.

- [ ] **Step 3: Implement.** Pass `timeout=timeout_s` to `audio.transcriptions.create`, and `extra_body={"sample_rate": …}` only when it is set.

- [ ] **Step 4: Update the callers** as the Interfaces block says: `session.py`, `ws.py`, `container.py`, the status route, and the tests that build a `Container` or a `ConversationSession`. Then run `just check-py` and `just test-py`; both pass.

- [ ] **Step 5: Commit**: `refactor(api): speech adapters take the model per call`.

---

### Task 6: `SpeechService`

**Files:**
- Create: `services/api/src/vt_api/services/speech.py`
- Test: `services/api/tests/unit/test_speech_service.py`, plus a fixture in `services/api/tests/conftest.py`

**Interfaces:**
- Consumes:
  - From Task 1: `SpeechSettings`, `SpeechSettingsView`, `SpeechModels`, `SpeechModel`, `Voice`, `VoicePreview`, `catalog`, `entry`, `entry_for`, `VoiceChoice`, `SessionSpeech`, `transcription_timeout_s` and `SpeechSettingsError`.
  - The ports from Tasks 2–5.
- Produces:
  ```python
  class SpeechService:
      def __init__(self, *, repository: SpeechSettingsRepository, stt: SpeechToText, tts: TextToSpeech,
                   recognition_server: SpeechModelServer, voice_server: SpeechModelServer,
                   files: ModelFiles | None, defaults: SpeechSettings) -> None
      async def view(self) -> SpeechSettingsView
      async def save(self, settings: SpeechSettings) -> SpeechSettingsView        # 422 if a model is not installed or the voice is not the model's
      async def models(self) -> SpeechModels
      async def download(self, key: str, activate: bool) -> SpeechModels          # 404 unknown key, 409 other download running / not manageable
      async def cancel_download(self) -> None
      async def uninstall(self, key: str) -> None                                 # 409 default, selected or downloading
      async def voices(self, model_id: str) -> list[Voice]
      async def preview(self, request: VoicePreview) -> bytes                     # WAV of PREVIEW_TEXT at 24 kHz
      async def for_session(self) -> SessionSpeech
      async def transcribe(self, wav: bytes, audio_s: float, model: str) -> str   # records the speed per model
      def synthesize(self, text: str, voice: VoiceChoice) -> AsyncIterator[bytes]
      async def status(self) -> SpeechStatus                                      # status of the *selected* models
      async def aclose(self) -> None                                              # cancels a running download
  PREVIEW_TEXT = "Hi! I'm your English tutor. Shall we practise together?"
  ```
- **Rules:**
  - **Manageable kind:** `files is not None` and that kind's `server.is_speaches()`.
  - **Downloads:**
    - The download runs as a background `asyncio.Task` owned by the service.
    - When it succeeds, the service checks `server.installed()` contains the model. If not, it sets `last_error`: "Downloaded, but Speaches does not see it: VT_SPEECH_MODELS_DIR must be the folder Speaches reads (see docs/configuration.md)".
    - When it succeeds and the intent is set, the service saves that kind's model.
    - For the voice kind, it keeps the current voice if `voices(new)` has it, else uses the first English voice.
  - **Intent:**
    - `pending` lists the model ids with an activate intent.
    - A `save()` that changes a kind's model clears that kind's pending intent.
    - A cancel clears it too.
    - Calling `download` again for the model already downloading only updates `activate`.
  - **Uninstall:** `server.unload(model_id)` first, then `files.delete(model_id)`.
  - **Measured speed:** per model, the total audio seconds and the total ms. `ms_per_audio_s = total_ms / total_audio_s`.
  - **`for_session()`:** a saved model that is no longer installed falls back to that kind's default, and the kind is listed in `missing`. `VoiceChoice.sample_rate_hz` comes from the catalog entry.

- [ ] **Step 1: Write the failing tests.** Use in-memory fakes for both servers and `ModelFiles`, the real `SqlSpeechSettingsRepository` over the `database` fixture, and `create_autospec` STT/TTS.
  - `test_view_defaults_then_saved`.
  - `test_save_refuses_a_model_that_is_not_installed` (422).
  - `test_save_refuses_a_voice_of_another_model` (422).
  - `test_models_merge_catalog_installed_downloading_and_measured`: one entry each in `installed`, `downloading` (with progress) and `available`. Exactly one `selected` per kind, `default` flags correct, and `ms_per_audio_s` after two `transcribe` calls (2 s audio and 1000 ms; 4 s and 3000 ms gives `ms_per_audio_s == 666.7` (4000/6), to one decimal).
  - `test_download_with_activate_selects_the_model_when_done`.
  - `test_download_seen_by_speaches_is_required` *(Review Focus 1)*.
  - `test_switching_to_piper_picks_its_voice` *(Review Focus 3)*.
  - `test_second_download_conflicts_same_one_updates_intent` *(Review Focus 5)*.
  - `test_uninstall_refuses_default_selected_and_downloading` *(Review Focus 5)*.
  - `test_uninstall_unloads_then_deletes`: the server fake records `unload` before the files fake records `delete`.
  - `test_choosing_another_model_drops_the_pending_activation`.
  - `test_cancel_drops_the_intent`.
  - `test_not_manageable_without_files_or_speaches`: download gives 409, and the `*_manageable` flags are false.
  - `test_for_session_falls_back_to_default_when_missing`.
  - `test_preview_is_a_wav_of_the_sample`: it is a RIFF header at 24000 Hz, with the TTS called with `PREVIEW_TEXT` and the given voice.
  - `test_transcribe_uses_the_growing_timeout`: the STT fake receives `timeout_s == transcription_timeout_s(audio_s)`.

- [ ] **Step 2: Run** `uv run pytest services/api/tests/unit/test_speech_service.py -q` and see them fail.

- [ ] **Step 3: Implement** `SpeechService`. Wrap the PCM from `synthesize` with `vt_api.domain.audio.to_wav(pcm, OUTPUT_SAMPLE_RATE_HZ)`.

- [ ] **Step 4: Run** the tests, then `uv run mypy services/api/src` for this module.

- [ ] **Step 5: Commit**: `feat(api): speech service with downloads and choices`.

---

### Task 7: HTTP routes and container wiring

**Files:**
- Modify: `services/api/src/vt_api/http/speech.py`, `services/api/src/vt_api/container.py`, `services/api/tests/integration/*.py` (Container construction)
- Test: `services/api/tests/integration/test_speech_api.py`

**Interfaces:**
- Consumes: `SpeechService` (Task 6), via `request.app.state.container.speech`.
- Produces the endpoints:

  | Method and path | Body | Answer |
  |---|---|---|
  | `GET /v1/speech/settings` | — | `SpeechSettingsView` |
  | `PUT /v1/speech/settings` | `SpeechSettings` | `SpeechSettingsView` |
  | `GET /v1/speech/models` | — | `SpeechModels` |
  | `POST /v1/speech/models/{key}/download` | `DownloadRequest` | **202** with `SpeechModels` |
  | `DELETE /v1/speech/models/{key}/download` | — | 204 |
  | `DELETE /v1/speech/models/{key}` | — | 204 |
  | `GET /v1/speech/voices?model=` | — | `list[Voice]` |
  | `POST /v1/speech/preview` | `VoicePreview` | `audio/wav` |
  | `GET /v1/speech/status` | — | as before, from `speech.status()` |

  `SpeechSettingsError` becomes `HTTPException(status, detail=message)`.
- Produces: `Container.speech: SpeechService`, wired in `build_container`:
  - a `SpeachesServer` for each URL, on a shared `httpx2.AsyncClient` that is closed on exit;
  - `HfModelFiles(settings.speech_models_dir)` when that is set, else `None`;
  - `defaults=SpeechSettings(...)` from `Settings`;
  - `speech.aclose` pushed onto the exit stack.

- [ ] **Step 1: Write the failing integration tests**, in the style of `test_learner_api.py`, with a container holding a real `SpeechService` over fakes:
  - the settings round trip;
  - a 422 for `max_turn_s: 10`;
  - download 202 and then a second 409;
  - cancel 204;
  - uninstall of the default 409;
  - `preview` content type `audio/wav`;
  - voices filtered;
  - status uses the selected models.

- [ ] **Step 2: Run** them and see them fail.

- [ ] **Step 3: Implement** the routes. Keep them thin; the logic stays in the service.

- [ ] **Step 4: Wire the container**, and update every integration test that builds a `Container`. Run `just check-py` and `just test-py`; both pass.

- [ ] **Step 5: Commit**: `feat(api): speech settings and model endpoints`.

---

### Task 8: Conversation session: speech choice, long turns, missing models

**Files:**
- Modify: `packages/contracts/src/vt_contracts/ws.py`, `services/api/src/vt_api/realtime/session.py`, `services/api/src/vt_api/http/ws.py`
- Test: `services/api/tests/unit/test_session.py`, `services/api/tests/integration/test_ws_api.py`

**Interfaces:**
- Consumes: `SpeechService.for_session`, `.transcribe` and `.synthesize` (Task 6).
- Produces:
  - `TranscriptFinal.cut: bool = False`.
  - In `ErrorCode`, `"audio_too_long"` is removed and `"speech_model_missing"` is added.
  - `ConversationSession(..., speech: SpeechService)` replaces the `stt=`, `tts=` and temporary `SessionSpeech` parameters. `MAX_SPEECH_S` is removed.
  - `Container` drops `stt`, `tts` and `session_speech`. The status route and the session go through `speech`.
  - Before `session.start`, the buffer limit is `defaults.max_turn_s`.

- [ ] **Step 1: Update the tests first.**
  - `test_a_long_turn_is_cut_not_lost` *(Review Focus 4)*:
    - With `max_turn_s=30`, send 31 s of PCM and commit.
    - The STT receives exactly 30 s, `TranscriptFinal.cut is True`, and no error is sent.
    - The service recorded `audio_s == 30`.
  - `test_missing_model_warns_at_start`: `for_session` returns `missing=("recognition",)`. Expect `ErrorEvent(code="speech_model_missing", retryable=True)`, and the message names Settings → Voice.
  - `test_session_uses_the_chosen_voice`: `synthesize` gets the `VoiceChoice` from `for_session`.
  - Remove the `audio_too_long` test.

- [ ] **Step 2: Run** `uv run pytest services/api/tests/unit/test_session.py -q` and see them fail.

- [ ] **Step 3: Implement.**
  - Read `for_session()` in `_start`, next to the profile, and keep it in `_Started`.
  - `audio()` stops buffering at the limit and remembers `cut`.
  - `_run_voice` calls `speech.transcribe(wav, audio_s, model)`.
  - `_Speaker` calls `speech.synthesize(text, voice)`.

- [ ] **Step 4: Run** the session and ws tests.

- [ ] **Step 5: Commit**: `feat(api): long turns are cut, not lost; per-session speech choice`.

---

### Task 9: Compose, justfile, the models folder, docs

**Files:**
- Modify: `compose.yaml`, `justfile`, `.gitignore`, `docs/configuration.md`, `docs/architecture.md`, `docs/roadmap.md`, `README.md`
- Create: `data/models/.gitkeep`

**Interfaces:**
- Consumes: `VT_SPEECH_MODELS_DIR` and `VT_MAX_TURN_S` (Task 1).
- Produces: one models folder shared by the api and Speaches, in development and in Compose.

- [ ] **Step 1: Compose.**
  - The `stt-cpu` and `stt-nvidia` volumes become `./data/models:/home/ubuntu/.cache/huggingface/hub`, and the `stt-models` volume is removed.
  - The api gets `VT_SPEECH_MODELS_DIR: /data/models`.
  - Update the comments.

- [ ] **Step 2: justfile.** `dev-api` sets `VT_SPEECH_MODELS_DIR` to `data/models` only when `os() == "linux"`, and leaves it empty otherwise; empty means unset (`env_ignore_empty`). Pick the just syntax that does this, then check it with `just --evaluate` and `just --show dev-api`.

- [ ] **Step 3: `.gitignore`.** Keep `data/models/` with its `.gitkeep`:
  ```
  data/*
  !data/.gitkeep
  !data/models/
  data/models/*
  !data/models/.gitkeep
  ```

- [ ] **Step 4: Docs.**
  - `configuration.md`: `VT_SPEECH_MODELS_DIR` (including the Linux-only note for `just dev-api`), `VT_MAX_TURN_S`, the new `VT_TTS_SPEED` range, and that `VT_STT_MODEL`, `VT_TTS_MODEL` and `VT_TTS_VOICE` are defaults until saved in Settings.
  - The "one-time re-download" note, and how to remove the old volume: `docker volume rm <project>_stt-models`.
  - `architecture.md`: an ADR row, "The api owns speech model files; Speaches only serves them". Phase 4 reuses it.
  - Roadmap: tick the items already done (see the 2026-10-23 review in the conversation: contracts, api wiring, the Phase 3 CI items) and add this feature.
  - README Voice section: Settings → Voice.

- [ ] **Step 5: Run** `just check-py`, `just test-py`, then `docker compose config -q` for each profile (`--profile cpu`, `nvidia`, `amd`, `external`). That command only validates; it builds nothing.

- [ ] **Step 6: Commit**: `feat: share the speech models folder with Speaches; document speech settings`.

---

### Task 10: Settings → Voice in the UI

**Files:**
- Modify:
  - `apps/desktop/src/features/settings/use-speech.ts`, `apps/desktop/src/features/settings/speech-section.tsx`
  - `apps/desktop/src/test/fake-api.ts`
  - `apps/desktop/openapi.json` and `apps/desktop/src/generated/api.d.ts` (via `just types`)
- Create: `apps/desktop/src/features/settings/speech-models.tsx`, `turn-length.tsx`, `voice-picker.tsx`
- Test: `apps/desktop/src/features/settings/speech-section.test.tsx` (extend), `voice-settings.test.tsx` (new)

**Interfaces:**
- Consumes: the endpoints of Task 7, through the generated `Schemas`.
- Produces, in `use-speech.ts`:
  - The existing `speechStatusQuery`.
  - `speechSettingsQuery`, `speechModelsQuery` and `voicesQuery(model)`.
  - `useSpeechModels()`, which refetches every 1000 ms while any model has `state === 'downloading'`.
  - `playPreview(body: VoicePreview): Promise<void>`, which fetches the WAV through `fetchClient` with `parseAs: 'blob'` and plays it with `new Audio(URL.createObjectURL(blob))`.

- [ ] **Step 1: Run `just types`** and commit the generated files with this task.

- [ ] **Step 2: Write the failing tests**, with `fakeApi` extended for the new endpoints, in the style of `learning-section.test.tsx`:
  - `lists recognition models with their state and size`: the rows show "Default" and "In use" badges, "Download (75 MB)" and a progress bar labelled with its percentage.
  - `selecting a model that is not installed downloads it and shows progress`: sends `POST …/download {activate: true}`, then the polled progress shows up, then "In use".
  - `cancel stops the download`: sends `DELETE …/download`.
  - `uninstall asks first`: the confirm dialog, then `DELETE /v1/speech/models/{key}`. There is no Uninstall on the default model.
  - `read-only when the server cannot manage models`: there are no Download or Uninstall buttons, and the explanation line is shown.
  - `turn length saves and explains the cost`:
    - Choosing `3 min` sends `PUT` with `max_turn_s: 180`.
    - With `ms_per_audio_s: 120`, the text says "about 22 s" (180 × 0.12, rounded).
    - Without a measurement, it says the estimate appears after a few voice turns.
    - Above 60 s, the extra sentence appears.
  - `voices are grouped and previewed`: there are groups "American" and "British" × "Female" and "Male". ▶ calls `POST /v1/speech/preview` with the selected speed.
  - `speed saves`: `tts_speed` is sent within 0.7–1.3.
  - `changes apply from the next conversation`: that note is visible.

- [ ] **Step 3: Run** `pnpm --filter @voice-tutor/desktop test -- speech voice-settings` and see them fail.

- [ ] **Step 4: Implement** the components.
  - Reuse `SegmentedControl`, `Button`, `Badge` and `Alert`.
  - Model rows are a radio group (`role="radiogroup"`, with labels "Speech recognition model" and "Voice model").
  - The readiness rows and the setup help that exist today stay at the top of the section.

- [ ] **Step 5: Run** `just check-ui` and `just test-ui` (coverage ≥ 97 %).

- [ ] **Step 6: Commit**: `feat(ui): choose speech models, voice and turn length`.

---

### Task 11: Practice page: cut turns and the missing-model warning

**Files:**
- Modify: `apps/desktop/src/features/practice/use-conversation.ts`, `apps/desktop/src/features/practice/turn-view.tsx`
- Test: `apps/desktop/src/features/practice/practice-voice.test.tsx`

**Interfaces:**
- Consumes: `TranscriptFinal.cut`, and the error code `speech_model_missing` (Task 8, regenerated in Task 10).
- Produces: `Turn.cut: boolean`. `audio_too_long` is removed from `SPEECH_ERRORS`.

- [ ] **Step 1: Write the failing tests.**
  - `a cut turn says so`: a `transcript.final` with `cut: true` renders "Cut at the turn limit", with a link to `/settings`.
  - `the missing-model warning shows`: an `error` event with `speech_model_missing` shows its message in the existing alert.

- [ ] **Step 2: Run** them and see them fail.

- [ ] **Step 3: Implement** both changes.

- [ ] **Step 4: Run** `just check-ui` and `just test-ui`.

- [ ] **Step 5: Commit**: `feat(ui): show cut turns and missing speech models`.

---

### Task 12: Whole-branch check and the PR

- [ ] **Step 1: Run** `just check-py`, `just test-py`, `just check-ui`, `just test-ui` and `just types`. The last must leave no diff.
- [ ] **Step 2: Push** with `SKIP=clippy,cargo-test git push -u origin feat/speech-settings`.
- [ ] **Step 3: Open the PR into `develop`.**
  - The body has a summary, what was verified, and what needs the maintainer.
  - What needs the maintainer: run `just voice` (the default models re-download once into `data/models`), then download and cancel `tiny.en` from Settings, and try a voice preview.
  - The body ends with "🤖 Generated with [Claude Code](https://claude.com/claude-code)".
- [ ] **Step 4: Wait** for CI to be green before reporting.
