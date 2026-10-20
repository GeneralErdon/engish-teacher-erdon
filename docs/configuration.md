# Configuration reference

All settings live in `.env` (start from [`.env.example`](../.env.example)). Docker Compose passes the file to `api` and `pron`; `just` loads it too.

Variables use the `VT_` prefix and are validated at startup by `vt_api.config.Settings` (pydantic-settings): a wrong type, an out-of-range number or an unknown enum value stops the service with a clear message. An empty value (`VT_X=`) means "use the default".

## api (`vt_api.config.Settings`)

| Variable | Type | Default | Description |
|---|---|---|---|
| `VT_PROFILE` | `cpu \| nvidia \| amd \| external` | `cpu` | Docker Compose profile used by `just up` / `just dev`; selects defaults shown in the UI |
| `VT_HOST` / `VT_PORT` | str / int | `127.0.0.1` / `8080` | Bind address of `vt-api`. The Docker image sets `0.0.0.0:8080` and compose publishes it on `127.0.0.1:8080`; change the `ports:` mapping in `compose.yaml` rather than these |
| `VT_CORS_ORIGINS` | JSON list of origins | desktop app + Vite dev server | Origins allowed to call the api cross-origin: `tauri://localhost` (Linux/macOS app), `http://tauri.localhost` (Windows app), `http://localhost:1420` (dev). The browser UI is same-origin and needs nothing |
| `VT_UI_DIR` | existing directory | unset | Built UI to serve at `/` (browser / home-lab mode). The Docker image sets `/app/ui` |
| `VT_LOG_LEVEL` | `DEBUG \| INFO \| WARNING \| ERROR \| CRITICAL` | `INFO` | Logging level |
| `VT_LLM_BASE_URL` | URL | `http://llm:8080/v1` | OpenAI-compatible chat endpoint |
| `VT_LLM_MODEL` | str | `gemma-3-4b-it-q4` | Model id as the endpoint expects it (matches the `cpu` profile; `gemma-3-12b-it-q4` for a 12–16 GB GPU) |
| `VT_LLM_API_KEY` | secret | empty | Cloud providers only |
| `VT_LLM_TEMPERATURE` | float 0–2 | `0.6` | Teacher creativity |
| `VT_STT_BACKEND` | `openai \| whispercpp` | `openai` | Selects STT adapter |
| `VT_STT_BASE_URL` | URL | `http://stt:8000/v1` | STT endpoint |
| `VT_STT_MODEL` | str | `large-v3-turbo` | Whisper variant |
| `VT_TTS_BASE_URL` | URL | `http://tts:8880/v1` | TTS endpoint |
| `VT_TTS_VOICE` | str | `af_heart` | Teacher voice |
| `VT_TTS_SPEED` | float (0, 4] | `0.95` | Slightly slower helps learners |
| `VT_PRON_BASE_URL` | URL | `http://pron:8001` | Pronunciation service |
| `VT_VAD_THRESHOLD` | float 0–1 | `0.5` | Silero speech probability threshold |
| `VT_VAD_MIN_SILENCE_MS` | int > 0 | `600` | Silence that ends a turn |
| `VT_LEARNER_L1` | ISO 639 code | `es` | Learner's native language (explanations and typical errors) |
| `VT_LEARNER_LEVEL` | `A1…C2` | `B1` | Starting level |
| `VT_NOTES_DIR` | path | `/data/notes` | Markdown notes output |
| `VT_DB_PATH` | path | `/data/progress.db` | SQLite database |
| `VT_KEEP_AUDIO` | bool | `false` | Keep raw audio for debugging |

`just dev-api` runs the api on your machine, so it overrides the model URLs with the ports Compose publishes on `127.0.0.1` (stt `8000`, llm `8081`, tts `8880`, pron `8001`) and stores data in `./data`.

## pron (`vt_pron.config.Settings`)

Own prefix, `VT_PRON_`, so both services can share one `.env` without clashing (`VT_PORT` is the api's).

| Variable | Type | Default | Description |
|---|---|---|---|
| `VT_PRON_HOST` / `VT_PRON_PORT` | str / int | `127.0.0.1` / `8001` | Bind address of `vt-pron`. The Docker image sets `0.0.0.0:8001`; keep `VT_PRON_BASE_URL` in sync if you change it |
| `VT_PRON_LOG_LEVEL` | as `VT_LOG_LEVEL` | `INFO` | Logging level |

## Docker Compose only

Read by `compose.yaml` to configure third-party containers; the Python services ignore them.

| Variable | Default | Description |
|---|---|---|
| `VT_LLM_HF_REPO` | `ggml-org/gemma-3-4b-it-GGUF` | GGUF repository llama.cpp downloads on first start (`cpu`, `amd` profiles). 12–16 GB GPU: `ggml-org/gemma-3-12b-it-GGUF` |
| `VT_LLM_CTX_SIZE` | `8192` | llama.cpp context size. Bigger costs VRAM/RAM for the KV cache |

llama.cpp serves the model under the name in `VT_LLM_MODEL`, so the api and the server always agree.
