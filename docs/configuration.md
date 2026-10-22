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
| `VT_LLM_PROVIDER` | `ollama \| ollama_cloud \| openai \| anthropic \| gemini \| openai_compatible \| anthropic_compatible` | `openai_compatible` | How to talk to `VT_LLM_BASE_URL` ([chat model providers](#chat-model-providers)) |
| `VT_LLM_BASE_URL` | URL | `http://llm:8080/v1` | Chat endpoint. Only applies until a provider is saved from the UI |
| `VT_LLM_MODEL` | str | `gemma-3-4b-it-q4` | Model id as the endpoint expects it (matches the `cpu` profile; `gemma-3-12b-it-q4` for a 12–16 GB GPU) |
| `VT_LLM_API_KEY` | secret | empty | Providers that need a key |
| `VT_LLM_TEMPERATURE` | float 0–2 | `0.6` | Teacher creativity |
| `VT_STT_BACKEND` | `openai \| whispercpp` | `openai` | Selects STT adapter |
| `VT_STT_BASE_URL` | URL | `http://stt:8000/v1` | STT endpoint |
| `VT_STT_MODEL` | str | `Systran/faster-distil-whisper-small.en` | Speaches model id. Downloaded once ([voice setup](#voice-setup)); on a GPU, `Systran/faster-whisper-large-v3-turbo` |
| `VT_TTS_BASE_URL` | URL | `http://tts:8000/v1` | TTS endpoint: the same Speaches as STT. Any server with an OpenAI-compatible `/audio/speech` that streams raw PCM at 24 kHz works, e.g. Kokoro-FastAPI on port `8880` |
| `VT_TTS_MODEL` | str | `speaches-ai/Kokoro-82M-v1.0-ONNX` | Kokoro on ONNX Runtime, downloaded once ([voice setup](#voice-setup)). Lighter (~120 MB): `speaches-ai/Kokoro-82M-v1.0-ONNX-int8`. Kokoro-FastAPI: `kokoro` |
| `VT_TTS_VOICE` | str | `af_heart` | Tutor voice: American (`af_*`, `am_*`) or British (`bf_*`, `bm_*`) English, e.g. `am_michael`, `bf_emma` |
| `VT_TTS_SPEED` | float 0.5–2.0 | `0.95` | Slightly slower helps learners |
| `VT_PRON_BASE_URL` | URL | `http://pron:8001` | Pronunciation service |
| `VT_VAD_THRESHOLD` | float 0–1 | `0.5` | Silero speech probability threshold |
| `VT_VAD_MIN_SILENCE_MS` | int > 0 | `600` | Silence that ends a turn |
| `VT_LEARNER_L1` | ISO 639 code | `es` | Learner's native language (explanations and typical errors) |
| `VT_LEARNER_LEVEL` | `A1…C2` | `B1` | Starting level. Changeable in the app (**Settings → Learning**), which wins |
| `VT_LEARNER_EXPLANATIONS` | `english \| native` | `native` | Language of correction explanations: English, or `VT_LEARNER_L1`. Changeable in the app |
| `VT_NOTES_DIR` | path | `/data/notes` | Markdown notes output |
| `VT_DB_PATH` | path | `/data/progress.db` | SQLite database |
| `VT_SETTINGS_PATH` | path | `/data/settings.json` | Settings saved from the UI, API keys included. Written with mode `0600` |
| `VT_LEARNER_PROFILE_PATH` | path | `/data/learner.json` | Level and explanation language saved from the UI |
| `VT_KEEP_AUDIO` | bool | `false` | Keep raw audio for debugging |

`just dev-api` runs the api on your machine, so it overrides the model URLs with the ports Compose publishes on `127.0.0.1` (stt and tts `8000`, llm `8081`, pron `8001`) and stores data in `./data`.

### Voice setup

Both directions of speech run on your machine in one [Speaches](https://speaches.ai) server, so your voice never leaves it: faster-whisper turns what you say into text, and [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) (82M parameters, on ONNX Runtime) gives the tutor its voice. Once:

```bash
docker compose --profile cpu up -d stt-cpu        # start Speaches (published on 127.0.0.1:8000)
export SPEACHES_BASE_URL=http://localhost:8000
uvx speaches-cli model download Systran/faster-distil-whisper-small.en   # speech recognition, ~340 MB
uvx speaches-cli model download speaches-ai/Kokoro-82M-v1.0-ONNX         # the tutor's voice, ~355 MB
```

**Settings → Voice** in the app checks each part (`GET /v1/speech/status`) and shows the commands for whatever is missing.

How a spoken turn travels:
- **You speak.** Press the microphone in **Practice**: the UI streams PCM16 at 16 kHz over `/ws/session` while you speak and sends `input.commit` when you press it again; the api wraps the audio as WAV and calls `POST {VT_STT_BASE_URL}/audio/transcriptions` with `language=en`.
- **The tutor answers out loud** (the **Voice on** button in Practice, remembered per device). As the reply streams from the chat model, each complete sentence goes to `POST {VT_TTS_BASE_URL}/audio/speech` (`response_format=pcm`), and its audio is forwarded to the UI as binary frames while the next sentence is still being written. The tutor starts talking after one sentence, not after the whole reply.
- **You interrupt** with the stop button, a new message or the microphone: the api cancels the reply and its voice, and the UI silences what was already queued.

Each reply shows its latency: `heard` (speech recognition), `first word`, `first sound` and `reply`. **Voice to voice**, the Phase 0 target (< 1.5 s), is `heard + first sound`.

### Chat model providers

Pick the chat model in the app under **Settings → Language model**, or with the `VT_LLM_*` variables. What you save in the app wins over the variables; **Reset** goes back to them.

| `VT_LLM_PROVIDER` | Base URL | API key | Notes |
|---|---|---|---|
| `ollama` | `http://localhost:11434` (from the Docker api: `http://host.docker.internal:11434`) | no | Models you pulled with Ollama. `/v1` at the end is accepted too |
| `ollama_cloud` | `https://ollama.com` | yes, from [ollama.com/settings/keys](https://ollama.com/settings/keys) | Free tier with usage limits |
| `openai` | `https://api.openai.com/v1` | yes | |
| `anthropic` | `https://api.anthropic.com` | yes | Messages API |
| `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai` | yes, from [Google AI Studio](https://aistudio.google.com/apikey) | Gemini's OpenAI-compatible endpoint; free tier with usage limits |
| `openai_compatible` | yours, usually ending in `/v1` | if the server asks | llama.cpp (the Compose default), LM Studio, vLLM, OpenRouter, Groq... |
| `anthropic_compatible` | yours, without `/v1` | if the server asks | Any server that speaks the Anthropic Messages API |

How the keys are handled:
- They go from the UI to the api once, are stored in `VT_SETTINGS_PATH` (mode `0600`, `./data` is gitignored) and never come back: the UI only learns *whether* a key is saved and its last four characters.
- A saved key is only sent to the URL it was saved with. Change the URL and you type the key again.
- The api never falls back to `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or other credentials in its own environment.
- `DELETE /v1/llm/settings` (**Reset** in the app) deletes the file, keys included.

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
