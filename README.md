# voice-tutor

> A private, self-hosted **English speaking coach**. Talk to it by voice, get grammar corrections, and practise pronunciation with **phoneme-level feedback**, all on your own machine.

Your audio never leaves your computer. No accounts, no telemetry, no subscriptions.

---

## Features

| | |
|---|---|
| 🗣️ **Free conversation** | Real-time voice chat with an AI teacher that adapts to your level and goals (job interviews, small talk, tech talks…). |
| ✍️ **Corrections** | Grammar, word choice and "sounds unnatural" notes, shown at the end of every turn or session, never interrupting your flow. |
| 🎯 **Pronunciation drills** | Read a target sentence; get a score per phoneme (correct / mispronounced / missing / extra) and a short explanation of how to fix it. |
| 📝 **Session notes** | Every session produces a Markdown note (summary, mistakes, words, sounds to practise) rendered in the UI and compatible with Obsidian. |
| 📈 **Progress** | Weakest phonemes over time, recurring grammar mistakes, vocabulary, streak. |
| 🔌 **Bring your own models** | Every AI component speaks an OpenAI-compatible API: run fully local (Ollama / llama.cpp, Whisper, Kokoro) or plug in a cloud key. |

## How it works

```
Desktop app (Tauri 2 + React) — or the same UI in a browser (home lab)
   │  mic capture · playback · Markdown notes · progress
   │  WebSocket: binary PCM16 audio + typed JSON events
   ▼
api (FastAPI) ── VAD · turn-taking · barge-in · teacher logic · notes · progress (SQLite)
   ├─► stt   speech-to-text   (Speaches / faster-whisper, or whisper.cpp)
   ├─► llm   chat model       (Ollama, llama.cpp server, LM Studio, or any OpenAI-compatible API)
   ├─► tts   text-to-speech   (Kokoro-FastAPI)
   └─► pron  pronunciation scoring (wav2vec2 phoneme recognition + alignment) — this repo
```

Details: [docs/architecture.md](docs/architecture.md).

## Quick start

**Requirements:** Docker with Compose v2, ~10 GB of free disk for models, a microphone.

1. Start the backend (models + API):

   ```bash
   git clone https://github.com/GeneralErdon/voice-tutor.git
   cd voice-tutor
   cp .env.example .env          # pick your hardware profile and models
   docker compose --profile cpu up -d   # the profile you set in VT_PROFILE: cpu | nvidia | amd | external
   ```

2. Use it:
   - **Desktop (recommended):** install the app for your OS from the Releases page (Windows `.msi`/`.exe`, Linux `.AppImage`/`.deb`/`.rpm`). It connects to `http://localhost:8080` by default.
   - **Browser / home lab:** open **http://localhost:8080** (the API also serves the same UI).

Models download on first start (progress is shown in the app and in `docker compose logs -f`).

### Pick a hardware profile

| Profile | Use it when | LLM runs on |
|---|---|---|
| `cpu` | Any machine; slow but works everywhere | CPU (small model) |
| `nvidia` | Linux or Windows (WSL2) with an NVIDIA GPU | CUDA in Docker |
| `amd` | **Linux** with an AMD GPU | Vulkan (llama.cpp) in Docker |
| `external` | macOS, **Windows + AMD**, or you already run Ollama / LM Studio | Your native install, reached via `host.docker.internal` |

Not sure? See [docs/hardware.md](docs/hardware.md).

### Using it from another device (phone, home lab)

Browsers only allow the microphone on `localhost` or over **HTTPS**. To use voice-tutor from another device on your network, use `tailscale serve` (a bundled Caddy reverse proxy with a local certificate is planned for Phase 3). Step-by-step instructions are in [docs/hardware.md#remote-access](docs/hardware.md#remote-access).

## Configuration

All settings live in `.env` (validated at startup, so the app refuses to boot with a clear message if something is wrong).

| Variable | Default | Description |
|---|---|---|
| `VT_PROFILE` | `cpu` | Hardware profile (see above). |
| `VT_LLM_BASE_URL` | `http://llm:8080/v1` | Any OpenAI-compatible chat endpoint. |
| `VT_LLM_MODEL` | `gemma-3-4b-it-q4` | Model name as the endpoint expects it (`gemma-3-12b-it-q4` on a 12–16 GB GPU). |
| `VT_LLM_API_KEY` | *(empty)* | Only for cloud providers. |
| `VT_STT_BASE_URL` | `http://stt:8000/v1` | Speech-to-text endpoint. |
| `VT_STT_MODEL` | `large-v3-turbo` | Whisper variant. |
| `VT_TTS_BASE_URL` | `http://tts:8880/v1` | Text-to-speech endpoint. |
| `VT_TTS_VOICE` | `af_heart` | Teacher voice. |
| `VT_PRON_BASE_URL` | `http://pron:8001` | Pronunciation scoring service. |
| `VT_NOTES_DIR` | `/data/notes` | Where session notes are written (mount it into your Obsidian vault if you like). |

The full reference is in [docs/configuration.md](docs/configuration.md).

## Results

Measured with `just eval` on the reference hardware. The table below is **generated** from `eval/results/latest.json`, so do not edit it by hand.

<!-- results:start -->
_No results yet. Run `just eval` (requires the L2-ARCTIC dataset, see [docs/evaluation.md](docs/evaluation.md))._
<!-- results:end -->

What is measured:
- **Mispronunciation detection**: precision / recall / F1 at phoneme level against human annotations (L2-ARCTIC, Spanish-L1 speakers).
- **Latency**: p50 / p95 per stage (VAD end → transcript → first LLM token → first audio byte) and voice-to-voice.

## Honest limitations

- Pronunciation scores are **reliable in drill mode** (known target sentence). In free conversation there is no reference text, so scoring uses the transcript as reference and is only indicative.
- Phoneme models are trained mostly on read adult speech; accuracy drops with noisy audio and very strong accents.
- Local models (12–14B) are good tutors but reason worse than frontier models. Plug in a cloud API if you need that.
- This is a learning aid, not a certified assessment.

## Development

Tasks run with [just](https://just.systems) (`uv tool install rust-just`), the same on Linux, macOS and Windows:

```bash
just setup      # uv sync + pnpm install + pre-commit hooks
just check      # ruff + mypy --strict + import-linter + eslint + tsc + cargo clippy
just test       # pytest + vitest + cargo test
just dev        # api (reload) + UI in the browser; models via docker compose
just desktop    # Tauri dev window against the local api
just            # list every recipe
```

Monorepo: Python services in a [uv](https://docs.astral.sh/uv/) workspace (`services/api`, `services/pron`, shared `packages/contracts`), the UI and desktop shell in a pnpm workspace (`apps/desktop`).

Conventions, tooling, testing strategy and typing rules: [docs/development.md](docs/development.md). Roadmap and progress: [docs/roadmap.md](docs/roadmap.md).

## Privacy

- Audio is processed in memory and discarded after the turn unless you enable `VT_KEEP_AUDIO=true` for debugging.
- Notes and progress are stored locally in `./data`.
- No analytics, no external calls except to the model endpoints you configure.

## Credits

Built on [FastAPI](https://fastapi.tiangolo.com/), [Silero VAD](https://github.com/snakers4/silero-vad), [Speaches](https://github.com/speaches-ai/speaches), [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), [llama.cpp](https://github.com/ggml-org/llama.cpp), [Ollama](https://ollama.com/) and wav2vec2 phoneme models. Check each model's license before redistributing it (see [docs/evaluation.md#licenses](docs/evaluation.md#licenses)).

## License

Not decided yet (MIT is the planned default). See [docs/roadmap.md](docs/roadmap.md).
