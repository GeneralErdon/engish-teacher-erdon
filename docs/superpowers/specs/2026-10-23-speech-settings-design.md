# Speech settings: models, voices and turn length from the UI

Status: approved in conversation on 2026-10-23, pending review of this document. One pull request into `develop`, on its own branch (`feat/speech-settings`), containing this document and the implementation.

## Why

Testing v0.1.0 on a laptop (Intel Core Ultra 7 258V, CPU only for speech) showed three gaps:

- **Recognition errors the learner cannot tell apart from pronunciation errors.** "job interviewer" was transcribed as "age of interviewer", and the tutor then corrected words the learner never said. The only speech model is `faster-distil-whisper-small.en`, picked for speed on CPU. The learner wants to choose a larger, more accurate model when the machine can afford it.
- **A hard 60-second limit per turn** (`MAX_SPEECH_S` in `realtime/session.py`). Answering an interview question ("tell me about yourself") takes 1–2 minutes, and going over the limit throws the whole turn away.
- **One fixed voice for the tutor.** `VT_TTS_VOICE` and `VT_TTS_SPEED` exist, but only as environment variables.

Every one of these should be a setting in **Settings → Voice**. The learner also gets honest feedback on what each choice costs: download size, and how much longer they wait for a reply.

## Goals

1. **Speech recognition model, chosen in the UI** from a short curated list. Each entry shows its size, English-only or multilingual, a speed/accuracy hint and its state. Models are downloaded **when the learner selects them**, by the backend, with a **progress bar** and a **Cancel** button. Installed models can be **uninstalled**. The default model is always installed and cannot be uninstalled.
2. **Tutor's voice model and voice, chosen in the UI**, with the same download flow for models. Voices are grouped by accent (American / British) and gender, and each has a **▶ preview** that speaks a sample sentence. A **speed** control (proposed in conversation; for slower listening at low levels) applies to every voice.
3. **Longest turn, chosen in the UI**, from 30 s to 5 min, with feedback on what a longer turn costs on this server. Going over the limit **keeps the turn**: the first part is transcribed and the learner is told the rest was cut.
4. Saved in the encrypted settings database, like the chat model and the learner profile. The environment variables stay as the defaults until something is saved.
5. Downloads happen **where the backend runs**: in a home lab, picking a model from a phone downloads it on the server.

## Non-goals

- Keeping the learner's recordings and replaying them. That was requested and is the next feature, not this one.
- Making replies faster: latency investigation, using the Intel Arc GPU or NPU (whisper.cpp with Vulkan, OpenVINO), streaming recognition.
- Other recognition engines (whisper.cpp, `VT_STT_BACKEND=whispercpp`), chat-model management, or arbitrary Hugging Face model ids typed by the learner.
- Tutor languages other than English, and resuming a download after the api restarts.

## Anti-goals (failure even if it "works")

- Downloads that block the api or freeze a conversation in progress. They run in the background, at low priority; they are not paused or throttled while the learner talks.
- Any path that leaves the learner without a working default model: uninstalling it, or a half-downloaded model selected as active.
- Losing a spoken turn because it was long.
- Showing the 651 recognition models Speaches knows about.
- Breaking the setups documented today: any OpenAI-compatible speech server (Kokoro-FastAPI, a remote Speaches) keeps working for transcription and synthesis (architecture decision #3).
- A setting that silently does not apply. If a change only takes effect in the next conversation, the UI says so.

## Constraints

- **Layering** (import-linter): HTTP routes → services → ports ← adapters. Contracts live in `vt_contracts`, and the UI types are regenerated with `just types`, which is checked in CI.
- **Coverage ≥ 97 %** in Python and in the UI, never lowered.
- **New dependencies:** the newest version published at least 7 days ago. `huggingface_hub` is expected; the builder confirms the version.
- **Database:** migrations in `adapters/sql/migrations/versions` (next is `v0002`), and the test that keeps `tables.py` and the migrations in sync.
- **UI:** text in English, shadcn/ui components, TanStack Query via `openapi-react-query` (`api.useMutation`, `api.queryOptions`), every change saved at once (as in `LearningSection`).
- **Resources:** the maintainer's machine is short on RAM. Do not run Rust/Tauri/Docker/`vite build` builds locally; CI runs them. GitHub Actions builds the installers only on releases. The PR runs the normal CI.
- **Speaches is the speech server the management features need.** Its API has list / download / delete for models (`/v1/models`, `/v1/registry`), voices (`/v1/audio/voices`) and loading / unloading (`/api/ps/{model}`). Its download reports **no progress and cannot be cancelled**, and that drives the design below.
- **Other OpenAI-compatible servers keep working** for the conversation, as today. Management is detected per kind (recognition, voice), since `VT_STT_BASE_URL` and `VT_TTS_BASE_URL` may point at different servers.
  - A kind is *manageable* only when `VT_SPEECH_MODELS_DIR` is set **and** its server answers the Speaches endpoints.
  - Otherwise that kind's settings are read-only: its current model, and its voices without accent or gender grouping when the server lists no such data.
  - Extra Speaches-only parameters, such as `sample_rate`, are sent only where the catalog entry needs them, and those entries are only offered on Speaches.

## Design

### Who owns the model files

**The api downloads models itself, into the folder Speaches reads.** Speaches only loads them.

- A new setting, `VT_SPEECH_MODELS_DIR`, points at a Hugging Face cache directory shared with Speaches.
  - Development: `data/models`.
  - Compose: `/data/models` in the api container. Speaches mounts the same host folder `./data/models` at `/home/ubuntu/.cache/huggingface/hub`, replacing the `stt-models` named volume.
  - So `just voice` + `just dev-api` and `just up` share one folder.
  - **Supported hosts:** Compose everywhere, where both processes are Linux containers on the same mount, and `just dev-api` on Linux. On Windows and macOS hosts, `just dev-api` leaves `VT_SPEECH_MODELS_DIR` unset (read-only lists), because the Hugging Face cache's symlinks, made inside a Linux container, are not reliable through a Windows or macOS bind mount. This is documented.
- `data/models/` is kept in git with a `.gitkeep` (as `data/` is), so Docker never creates it root-owned.
- Downloads use `huggingface_hub` with `cache_dir=VT_SPEECH_MODELS_DIR`, so the files land in the exact layout Speaches looks for.
- **Progress:** bytes on disk against the total from the Hugging Face API (file sizes of the repo revision). How the bytes are counted is left to the builder, after a quick check against the current `huggingface_hub`, Xet storage included. Two candidates: a hook in `huggingface_hub`'s progress reporting, or measuring the files in the repo's cache folder, `.incomplete` files included.
- **Cancel:** the download runs where it can be stopped for real. The suggestion is a child process (`python -m …`) that the api terminates, then removing the partial files. The builder may pick another mechanism if it truly stops the transfer.
- **Disk space** is checked before starting: a download that would not fit is refused with the size it needs.
- **One download at a time.** Starting another while one runs is refused (409) with a clear message.
- **Activation belongs to the backend.** Selecting a model that is not installed starts its download with the intent "make it active when done".
  - The api applies the intent when the download completes, even if the tab was closed or the phone locked.
  - Choosing another installed model before then cancels the intent, so the latest choice wins. The download still completes and the model stays installed.
  - Cancelling the download drops the intent.
- **After a download, the api checks that Speaches lists the model.** If it does not, the folder is not shared with Speaches (for example, a Speaches on another machine), and the error says so and points to `VT_SPEECH_MODELS_DIR`.
- **Uninstall:** first ask Speaches to unload the model (`DELETE /api/ps/{id}`), then delete its cache folder.
- **Without `VT_SPEECH_MODELS_DIR`** (e.g. a Speaches the api cannot reach on disk), the lists are read-only. They show what Speaches has installed, and the learner can choose among installed models and voices. Download and uninstall are hidden, with one line explaining why.
- **The default models are the environment's** (`VT_STT_MODEL`, `VT_TTS_MODEL`).
  - `just voice` keeps pre-downloading them through Speaches' `PRELOAD_MODELS`, so a fresh install works without visiting Settings.
  - They cannot be uninstalled.
  - If the environment names a model outside the curated list, it still appears, labelled as coming from the configuration.
- **Moving off the old volume:** the models in the old `stt-models` volume (~700 MB) are downloaded again once. The docs say so and show how to remove the old volume.

### Curated catalog

A list in the api (one module, easy to edit), with an id, a label, a hint and an approximate size. Sizes shown before download come from the catalog; the real total comes from Hugging Face when the download starts. All ids below were checked against the Speaches registry on 2026-10-23.

**Speech recognition** (faster-whisper / CTranslate2). The api always sends `language="en"`, so English-only models are preferred at each size:

| Id | Hint |
|---|---|
| `Systran/faster-whisper-tiny.en` | Fastest, least accurate |
| `Systran/faster-whisper-base.en` | Very fast |
| `Systran/faster-distil-whisper-small.en` | **Default.** Fast, good for most accents |
| `Systran/faster-whisper-small.en` | A bit slower, a bit more accurate |
| `Systran/faster-distil-whisper-medium.en` | More accurate; slower on CPU |
| `Systran/faster-whisper-medium.en` | Accurate; slow on CPU |
| `Systran/faster-distil-whisper-large-v3` | Very accurate; GPU recommended |
| `deepdml/faster-whisper-large-v3-turbo-ct2` | Most accurate; GPU recommended (multilingual) |

**Tutor's voice:**

| Id | Hint |
|---|---|
| `speaches-ai/Kokoro-82M-v1.0-ONNX` | **Default.** Natural; 28 English voices (American and British, female and male) |
| `speaches-ai/Kokoro-82M-v1.0-ONNX-int8` | Same voices, smaller and faster on CPU, slightly lower quality |
| `speaches-ai/piper-en_US-lessac-medium` | Very light and fast, more robotic; one voice |
| `speaches-ai/piper-en_US-ryan-medium` | Same, male |
| `speaches-ai/piper-en_GB-alba-medium` | Same, British female |
| `speaches-ai/piper-en_GB-alan-medium` | Same, British male |

**Voices:**
- They come from Speaches (`/v1/audio/voices`) for installed models, filtered to English (`en-us`, `en-gb`), with language and gender.
- Changing the voice model keeps the current voice if the new model has it, else picks the new model's first English voice.
- Piper generates 22.05 kHz audio. The api requests `sample_rate=24000`, a parameter Speaches accepts, so every model streams at `OUTPUT_SAMPLE_RATE_HZ` and the UI player is unchanged.

### Settings that are saved

A new single-row table, `speech_settings` (migration `v0002`), holding:
- `stt_model`
- `tts_model`
- `tts_voice`
- `tts_speed`: 0.7–1.3, default `VT_TTS_SPEED` (0.95)
- `max_turn_s`: 30–300, default from a new `VT_MAX_TURN_S` = **120**

A `SpeechService` follows the `LearnerService` pattern (repository port, environment defaults, a view with `source: "environment" | "saved"`). Saving validates:
- the models are installed;
- the voice belongs to the voice model;
- the values are in range.

A refused save says why.

### Using the settings

- `OpenAISpeechToText.transcribe` and `OpenAITextToSpeech.synthesize` take the model (and voice and speed) per call, instead of fixing them at construction. Their ports change accordingly.
- The conversation session reads the speech settings at `session.start`, as it reads the learner profile. A change applies from the **next** conversation; the Settings UI says so. The voice on/off toggle keeps working mid-session, as today.
- **A saved model that has gone missing** (folder wiped, removed with Speaches' own tools) does not break voice turns.
  - The session falls back to that kind's default model, which is always installed.
  - It sends a non-blocking warning through the existing error event (`retryable`). The Practice page already shows those: the model in use, and where to fix it (Settings → Voice).
  - The Settings view marks the saved choice as missing.
- **Long turns:**
  - The session buffers up to `max_turn_s`.
  - Over the limit, it keeps the first `max_turn_s`, transcribes them, and marks the transcript as cut: a new field on `TranscriptFinal`. The UI shows a short note under that message, pointing to Settings → Voice.
  - The `audio_too_long` error is no longer sent for long turns.
  - The transcription timeout grows with the length of the audio, instead of the fixed 60 s. The builder picks the formula; something like 30 s + 3 × the audio length.
- **Measured speed:**
  - After each transcription, the service records the audio length and the time it took, per model (in memory; a restart forgets it).
  - The turn-length control shows the estimate for the selected length. For example: "With distil-small.en, 2 min of speech take about 14 s to transcribe here."
  - Until a model has been measured, it says the estimate appears after a few voice turns.
  - Above 1 min, it also says plainly that the tutor starts answering only after the whole turn is transcribed.

### API (shapes are the builder's, within these lines)

| Endpoint | Purpose |
|---|---|
| `GET /v1/speech/settings` / `PUT` | The saved choices (view with `source`) |
| `GET /v1/speech/models` | Catalog for both kinds, each entry with state and other fields (below) |
| `POST /v1/speech/models/{key}/download` | Start a download (202); 409 if one is running; 507 or a clear 4xx if the disk is too small |
| `DELETE /v1/speech/models/{key}/download` | Cancel |
| `DELETE /v1/speech/models/{key}` | Uninstall; refused for a default or a selected model |
| `GET /v1/speech/voices?model=…` | English voices of an installed voice model |
| `POST /v1/speech/preview` | Speak a fixed sample sentence with `{model, voice, speed}`; returns audio the browser can play |
| `GET /v1/speech/status` | Unchanged readiness check |

Each `GET /v1/speech/models` entry carries:
- its state: `installed`, `downloading` (with bytes done and total) or `available`;
- `default`, `selected` and `manageable` flags;
- the measured speed, for recognition models.

`{key}` is a short slug from the catalog (e.g. `whisper-small-en`), not the Hugging Face id, so URLs stay simple. The UI polls `GET /v1/speech/models` about once a second while a download runs.

### UI: Settings → Voice

The current readiness rows and the "one-time setup" help stay at the top. Below them come three groups, each change saved at once:

1. **Speech recognition:** the model list as selectable rows.
   - Each row shows the label, the size, an English-only or multilingual tag, the hint and, once measured, the speed.
   - Actions by state: *Use* (installed), *Download (X MB)*, a progress bar with *Cancel*, and *Uninstall* (confirm first). There are badges for *Default* and *In use*.
   - Selecting an uninstalled model downloads it and makes it active when the download finishes, as agreed in conversation. Cancelling leaves the previous model active.
2. **Longest turn:** a segmented control (30 s · 1 min · 2 min · 3 min · 5 min) with the feedback text described above.
3. **Tutor's voice:**
   - The same model list.
   - The voice picker, grouped American / British × female / male, each with ▶ preview.
   - A speed control (0.7×–1.3×) whose preview uses the selected voice.

On the Practice page, the only changes are the "cut" note on long transcripts, and the missing-model warning through the error display it already has.

### Docs

- `docs/configuration.md`: `VT_SPEECH_MODELS_DIR`, `VT_MAX_TURN_S`, and the speech variables as defaults.
- README voice section: Settings → Voice, and the one-time re-download.
- `compose.yaml` comments, and a short ADR row in `docs/architecture.md` ("the api owns speech model files; Speaches only serves them"). The ADR notes that Phase 4 reuses the same download manager.
- The roadmap.

## Decisions made in conversation

- Models download on selection, from Settings, by the backend, with Cancel and Uninstall. The small default model is always there.
- The tutor's voice is part of it: model, voice, and speed.
- The turn length is a setting, not an environment variable, with feedback on what longer turns cost.
- Everything ships in one pull request, on its own branch, with no installer builds in CI.

## Calls I made (the maintainer may overrule)

- The curated lists above, including Kokoro int8 and four Piper voices.
- The api, not Speaches, downloads models, because Speaches' download has no progress and no cancel.
- The shared `data/models` folder replaces the `stt-models` volume, at the cost of one re-download.
- 120 s as the default longest turn.
- Changes apply from the next conversation.
- One download at a time.
- In-memory speed measurements.
- Read-only lists when the api cannot reach the models folder, or when the server is not Speaches.
- *After review:*
  - Other OpenAI-compatible servers keep working, with management only on Speaches.
  - Downloads run at low priority, with no throttling while talking.
  - The backend activates a model when its download finishes, and the latest choice wins.
  - A missing saved model falls back to the default, with a warning.
  - The shared folder works under Compose everywhere and with `just dev-api` on Linux.

## Left to the builder

- Exact request/response shapes, the catalog module layout and the slugs.
- The progress-counting and cancellation mechanism, after verifying `huggingface_hub`'s current behaviour (Xet included) against the constraints above.
- The transcription-timeout formula, and the polling interval.
- UI component structure, as long as it follows the existing settings sections.
- How to test downloads without the network: fakes behind a port, as the other adapters do.
