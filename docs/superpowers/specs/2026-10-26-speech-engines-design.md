# Speech engines: CPU or GPU (Vulkan) speech recognition, chosen in the UI

Status: approved on 2026-10-26, in conversation ("adelante el selector de motor, … vulkan para las GPU, el NPU puede ir después"), and the design summary below ("si asi vamos bien"). One pull request into `develop`, on its own branch (`feat/speech-engines`), containing this document and the implementation.

## Why

Speech recognition runs in Speaches, whose engine (faster-whisper / CTranslate2) only uses the CPU or an NVIDIA GPU. The maintainer's machines have an **AMD RX 9060 XT** (desktop) and an **Intel Arc 140V iGPU** (laptop, Core Ultra 7 258V). Neither is used today.

Recognition is the biggest steady cost of a voice turn: 2.5–4.4 s of the ~7 s measured voice-to-voice on the laptop's CPU. It is also why the default model is a small one that mishears ("age of interviewer" for "job interviewer").

**whisper.cpp built with Vulkan** runs on AMD, Intel and NVIDIA GPUs. The official image `ghcr.io/ggml-org/whisper.cpp:main-vulkan-<sha>` exists, and its server can answer at `/v1/audio/transcriptions`, the protocol the api already speaks.

This is also the first brick of the **Phase 4 all-in-one**, where the installed app (AppImage, Windows setup) starts the backend itself on the same machine, without Docker. There, the same whisper.cpp engine runs as a native sidecar. Docker Compose stays the way to run the backend on any server.

## Goals

1. **An engine choice in Settings → Voice:**
   - **Speaches**: what runs today. The CPU, or an NVIDIA GPU with the `nvidia` profile.
   - **whisper.cpp (GPU, Vulkan)**: AMD and Intel GPUs.

   Only engines that are running can be chosen. The other one is shown disabled, with how to start it.
2. **Each engine has its own curated model list**, with the same Download / Cancel / Uninstall flow and measured speed as today. The whisper.cpp models are GGML files.
3. **Switching engine or model needs no restart.** It applies from the next conversation, like every speech setting. Switching the whisper.cpp model reloads it in the running server.
4. **If the chosen engine is not running when a conversation starts,** recognition falls back to Speaches with its model, and the learner gets a warning, as a missing model does today.
5. **Starting the GPU engine is one command:** `just voice gpu`. It starts Speaches (the tutor's voice still runs there) and the whisper.cpp Vulkan server, and pre-downloads the GPU engine's default model.

## Non-goals

- The NPU (OpenVINO) and the tutor's voice on GPU. Kokoro stays on Speaches.
- GPUs inside Docker on Windows or macOS. Docker exposes only NVIDIA there. Native sidecars come in Phase 4.
- The api starting or stopping containers. That would need the Docker socket, which is root on the host.
- Native sidecars and packaging (Phase 4). Changing the `nvidia` or `amd` chat-model profiles.

## Anti-goals

- Breaking or slowing the Speaches path, or making the GPU engine required for anyone.
- Downloading the whole `ggerganov/whisper.cpp` repository (33 model files, many GB) when the learner picks one model.
- Uninstalling one GGML file and deleting the others that share the repository folder.
- A conversation that fails because the GPU container is down.

## Constraints

The same as the speech-settings feature. They are in `docs/superpowers/plans/2026-10-26-speech-settings.md`, under "Global Constraints":
- coverage ≥ 97 %;
- import-linter layering;
- new dependencies and Docker image tags at least 7 days old;
- no builds, Docker pulls or model downloads on the maintainer's machine without asking;
- UI text in English;
- every change saves at once.

Pin the whisper.cpp image by a `main-vulkan-<sha>` tag (with its digest) that is at least 7 days old.

## Design

### Engines

| Engine id | Server | Recognition models | Lists its models? | Switching models |
|---|---|---|---|---|
| `openai` (label "Speaches") | Speaches, `VT_STT_BASE_URL` | the current catalog (CTranslate2 repos) | yes: `/v1/models` | per request: the `model` field |
| `whispercpp` (label "whisper.cpp · GPU") | whisper.cpp `whisper-server`, Vulkan build, `VT_STT_GPU_BASE_URL` | GGML files from `ggerganov/whisper.cpp` | no: installed means the file is complete in the shared cache | `POST /load` with the file's path as the server sees it |

**The existing setting is reused.** `VT_STT_BACKEND` (`openai | whispercpp`, default `openai`) already exists unused and becomes the **default engine**.

**New settings:**

| Variable | Compose | Development |
|---|---|---|
| `VT_STT_GPU_BASE_URL` | `http://stt-gpu:8080/v1` | `http://localhost:8002/v1` |
| `VT_STT_GPU_MODELS_ROOT` (where the whisper.cpp server sees the shared models folder) | `/models` | `/models` |
| `VT_STT_GPU_MODEL` (the GPU engine's default model) | — | — |

**Default GPU model.** `ggerganov/whisper.cpp/ggml-small.en-q8_0.bin`, about 260 MB. My call: it is more accurate than today's CPU default and small enough to pre-download. `large-v3-turbo-q5_0` is offered as the accurate choice.

**When an engine is running.** Speaches: its server answers. whisper.cpp: its server answers a cheap request. There is no documented health route, so the builder checks the server source for one, or uses a cheap request.

### Model ids and files

- A GPU model id is `<repo>/<file>`, for example `ggerganov/whisper.cpp/ggml-small.en-q8_0.bin`. The catalog marks GGML entries as single files.
- **Download.** The download manager (`HfModelFiles`) gains single-file downloads, with `snapshot_download(..., allow_patterns=[file])`. Progress counts that file's bytes.
- **What "partial" and "installed" mean for single files:**
  - The api's marker names the file it is downloading, so `incomplete()` reports that model id.
  - Installed means the file's snapshot entry resolves to a complete blob.
- **Uninstall** removes only that file's snapshot entry and its blob. When no file is left, it removes the repository folder too.

### Saved settings

- Migration `v0003` adds to `speech_settings`:
  - `stt_engine`, with values `openai | whispercpp`;
  - `stt_gpu_model`, the selected GGML model.
- `stt_model` stays the Speaches model.
- **Why two model columns.** Each engine keeps its own choice, so going back to Speaches restores the learner's previous Speaches model.
- **Validation** follows the "only what changed" rule from the speech-settings fix wave:
  - Switching to an engine that is not running is refused with 409 and a message on how to start it.
  - Choosing a GGML model that is not installed is refused with 422, as today.

### Using it

- `for_session()` resolves the engine:
  - If the saved engine is `whispercpp` and its server answers, the session uses the GPU model.
  - Otherwise it uses Speaches with `stt_model` (falling back to its default, as now). A new warning, `speech_engine_unavailable`, works like `speech_model_missing`: retryable, its message names the engine and says how to start it.
- **The GPU model is loaded when the conversation starts.** `for_session()` always asks the whisper.cpp server to load the chosen model (`/load`), because no route reports the loaded model: a server restarted since the last conversation holds its startup model again.
  - The server exits if `/load` cannot open a model (read in its source; for example, not enough GPU memory). Loading at the start catches that before the learner speaks, and the session falls back to Speaches with the warning.
- **Mid-conversation fallback.** If the GPU server becomes unreachable during a conversation (a connection error or refusal, not an HTTP error answer), that turn is transcribed by Speaches instead.
  - The session stays on Speaches until the conversation ends; the GPU is not tried again on every turn.
  - It sends `speech_engine_unavailable` once.
  - The GPU client uses a short connect timeout (a few seconds), so a dead server fails fast. A server that accepts the connection but answers with an error or hangs past the transcription timeout stays `stt_failed`, as today.
- **A whisper.cpp adapter, with the `SpeechToText` port unchanged:**
  - It transcribes through `/v1/audio/transcriptions`, with the same WAV and `language=en`. It may reuse the OpenAI adapter if the server's JSON matches; otherwise it is a small dedicated adapter. Verify the response shape in the server source.
  - A transcription calls `/load` first only when its model differs from the one the adapter last loaded (a conversation start always loads, above). Loads and transcriptions are serialised with a lock, and the adapter tracks the loaded model.
  - A failed load is a `ProviderError`, so the turn reports `stt_failed`.
- **Measured speed** stays keyed by model id. The ids are distinct per engine, so the turn-length estimate follows the engine automatically.
- **Status** (`/v1/speech/status`) reports the recognition engine in use and its model.

### Starting it

- **Compose.** A service `stt-gpu`:
  - image: the pinned whisper.cpp Vulkan tag;
  - profiles `[gpu, amd]`. The `amd` profile is "Vulkan for everything", so `just up amd` and `just dev` with `VT_PROFILE=amd` start it with no other change (the desktop with the RX 9060 XT). `VT_PROFILE` stays a single value;
  - devices: `/dev/dri`;
  - volume: `./data/models:/models`;
  - port: `127.0.0.1:8002:8080`;
  - command: `whisper-server` with `--host 0.0.0.0 --port 8080 --request-path /v1 --inference-path /audio/transcriptions -m <default model path>`. Plus whatever the server needs to accept our WAV; the builder checks `--convert` and `--tmp-dir` against the server source.
  - The api gets `VT_STT_GPU_BASE_URL`, and the models folder is already shared.
- **The default model is present before the server starts.**
  - `just voice` takes an optional argument: `just voice gpu` runs Compose with the configured profile plus `--profile gpu`, starting `stt-cpu` and `stt-gpu` (the laptop with Ollama Cloud and `VT_PROFILE=cpu`). Before that it downloads the default model into `data/models` in the Hugging Face cache layout, on the host. Use `uvx --from huggingface-hub==2.2.0 hf download …` or the api's own worker module. Then it starts `stt-cpu` and `stt-gpu`.
  - A Compose-only start (`just up` with the `gpu` profile) needs the same guarantee, through a one-shot init service or a documented step. The builder picks the simpler of the two that works without the host's Python.
- **Linux only.** The docs say so: Docker on Windows and macOS has no Vulkan GPU, and Phase 4 brings the native engine.
- **Intel and AMD inside the container** need the image's Mesa Vulkan drivers (RADV for AMD, ANV for Intel). Check the image's Dockerfile (`.devops/main-vulkan.Dockerfile` in whisper.cpp) to confirm both are installed.

### UI: Settings → Voice

**Above the recognition model list,** a segmented control "Engine" with two options:
- `Speaches · CPU`. The hint says it uses an NVIDIA GPU with the `nvidia` profile.
- `whisper.cpp · GPU`. When it is not running, it is disabled and shows: "Start it with `just voice gpu` (Linux, AMD or Intel GPU)".

**The model list below** shows the selected engine's catalog, with the same rows, actions, confirmations and measured speed as today.

**The readiness rows** name the engine in use.

The Practice page shows the new warning through the existing alert, as it does for `speech_model_missing`.

### Docs

- `docs/configuration.md` (the new variables) and `docs/hardware.md` (the `amd` profile row now points at the real GPU engine; how to use the RX 9060 XT and the Arc iGPU).
- The README voice section.
- An ADR row: "Speech recognition engines: Speaches and whisper.cpp (Vulkan) behind one port; the api switches between running servers and never manages containers". Phase 4 runs the same whisper.cpp engine natively.
- The roadmap: Phase 0's latency item gets a line saying to compare CPU and GPU with the turn metrics.

## Calls I made (the maintainer may overrule)

- **Engines and the default model:**
  - The engine ids reuse `VT_STT_BACKEND` (`openai`, `whispercpp`), with the labels "Speaches" and "whisper.cpp · GPU".
  - The default GPU model is `ggml-small.en-q8_0`.
- **GPU model catalog,** about six entries:
  - `base.en`;
  - `small.en-q8_0`;
  - `medium.en-q5_0`;
  - `large-v3-turbo-q5_0`;
  - `large-v3-turbo-q8_0`;
  - `large-v3-turbo`.

  The builder checks the exact file names against the Hugging Face repo listing.
- **Saved settings:** one model column per engine, so each engine keeps its own choice.
- **Fallback:** a GPU engine that is not running falls back to Speaches, with a warning.
- **Starting:** `just voice gpu` starts both servers. The api never starts containers.
- **Scope:** recognition only; the tutor's voice stays on Speaches.
- *After review:*
  - The GPU model is loaded when the conversation starts.
  - If the GPU server becomes unreachable mid-conversation, that turn goes to Speaches, and the conversation stays there.
  - `stt-gpu` is in the profiles `[gpu, amd]`. `just voice gpu` adds the `gpu` profile, so `VT_PROFILE` stays a single value.

## Left to the builder

- **whisper.cpp facts to verify in its server source,** not by running it, since pulling images needs the maintainer:
  - the response shape;
  - the health check;
  - `/load` semantics, and how long a load blocks;
  - the audio options.
- **Mechanics:**
  - the exact shapes of the new contract fields;
  - the adapter split;
  - the init mechanism for a Compose-only start;
  - the single-file additions to the download manager, as long as uninstall never deletes sibling files.
- **Real hardware:** the image pin, and a manual test plan for the maintainer on both machines. The plan covers:
  - `just voice gpu`;
  - picking the engine;
  - comparing the `heard` times on CPU and GPU;
  - switching GGML models;
  - stopping `stt-gpu` mid-session and checking the fallback warning.
