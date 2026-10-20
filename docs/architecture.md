# Architecture

## Goals and non-goals

**Goals**
- Natural voice conversation with < 1.5 s voice-to-voice latency on a mid-range GPU.
- Phoneme-level pronunciation feedback that is *measured*, not guessed.
- Runs the same on Linux, Windows and macOS; installable with one command.
- Every model is swappable (local ↔ cloud) through configuration only.

**Non-goals (for now)**
- Multi-user accounts or authentication (single user / trusted LAN).
- Mobile apps (the web UI is responsive and works on phones over HTTPS).
- Always-on wake-word listening.

## Components

| Component | Owner | Responsibility | Interface |
|---|---|---|---|
| `desktop` | this repo | **Tauri 2** shell (Rust) around the React UI: native window, installers, mic permission handling, optional native audio capture | Hosts `ui` |
| `ui` | this repo | React + TypeScript: mic capture (AudioWorklet), playback, conversation, Markdown notes viewer, progress. Runs inside `desktop` **and** in a plain browser (served by `api`) | WebSocket + REST to `api` |
| `api` | this repo | Realtime session (VAD, turn-taking, barge-in), teacher logic, notes, progress, persistence | FastAPI: REST + `/ws/session` |
| `pron` | this repo | Pronunciation scoring: G2P → phoneme recognition → alignment → per-phoneme verdicts | REST `POST /v1/score` |
| `stt` | third party | Speech-to-text (Speaches/faster-whisper or whisper.cpp) | OpenAI `/v1/audio/transcriptions` (or whisper.cpp `/inference` via adapter) |
| `llm` | third party | Chat model (Ollama, llama.cpp server, LM Studio, cloud) | OpenAI `/v1/chat/completions` (streaming) |
| `tts` | third party | Text-to-speech (Kokoro-FastAPI) | OpenAI `/v1/audio/speech` (streaming PCM) |

Only `api`, `pron`, `ui` and `desktop` contain our code. Everything else is replaceable infrastructure.

## Design principles

1. **Ports and adapters (hexagonal).** The domain (`teacher`, `sessions`, `progress`) depends on `Protocol` interfaces (ports). HTTP clients, databases and model servers are adapters. Swapping Ollama for a cloud API is a new adapter or just a new URL, never a domain change.
2. **Typed boundaries.** Every message crossing a process boundary is a Pydantic model. TypeScript types for the browser are generated from the same JSON Schema, so there is a single source of truth.
3. **Pure core, async shell.** Scoring, corrections parsing and progress aggregation are pure functions, easy to unit test. I/O lives at the edges.
4. **Cancellation is a feature.** Barge-in cancels LLM and TTS tasks through `asyncio` task groups; every stage must be cancel-safe.
5. **Fail loudly at startup.** Configuration is validated with `pydantic-settings`; health checks verify each dependency before accepting sessions.

## Repository layout

```
voice-tutor/
├── README.md
├── compose.yaml                 # all services; hardware selected with --profile
├── .env.example
├── justfile                     # single entry point for dev tasks (Linux, macOS, Windows)
├── pyproject.toml               # uv workspace root + shared ruff/mypy/pytest/import-linter config
├── uv.lock
├── .python-version              # 3.14 (see docs/development.md#toolchain)
├── package.json                 # pnpm workspace root (pins pnpm via packageManager)
├── pnpm-workspace.yaml
├── pnpm-lock.yaml
├── .nvmrc                       # Node 24 LTS
├── rust-toolchain.toml          # pinned Rust + rustfmt + clippy
├── .pre-commit-config.yaml
├── .dockerignore                # build context is the repo root
├── .github/
│   ├── dependabot.yml           # weekly grouped updates per ecosystem
│   └── workflows/
│       ├── ci.yml               # lint, typecheck, tests (Rust on Linux + Windows), image builds
│       └── release.yml          # multi-arch images to GHCR + desktop installers on tag
├── docker/
│   ├── caddy/Caddyfile          # optional HTTPS for LAN access
│   └── whisper-vulkan/Dockerfile# whisper.cpp built with Vulkan (AMD/Intel)
├── packages/
│   └── contracts/               # shared Pydantic models (WS protocol, pron API)
│       └── src/vt_contracts/
│           ├── ws.py            # discriminated unions of client/server events
│           ├── pron.py          # ScoreRequest / ScoreResponse
│           ├── health.py        # /healthz response shared by api and pron
│           └── audio.py         # audio format constants (sample rates, frame size)
├── services/
│   ├── api/
│   │   ├── Dockerfile           # uv multi-stage; also builds the UI for browser mode
│   │   ├── pyproject.toml
│   │   ├── src/vt_api/
│   │   │   ├── __main__.py      # `vt-api`: uvicorn configured from Settings
│   │   │   ├── main.py          # app factory, lifespan, router wiring, UI static files
│   │   │   ├── config.py        # Settings (pydantic-settings)
│   │   │   ├── container.py     # dependency wiring: ports → adapters
│   │   │   ├── domain/          # entities & value objects (Session, Turn, Correction, PhonemeScore…)
│   │   │   ├── ports/           # Protocols: SpeechToText, ChatModel, TextToSpeech,
│   │   │   │                    #            PronunciationScorer, NotesRepository, ProgressRepository
│   │   │   ├── adapters/
│   │   │   │   ├── openai_stt.py
│   │   │   │   ├── whispercpp_stt.py
│   │   │   │   ├── openai_chat.py
│   │   │   │   ├── openai_tts.py
│   │   │   │   ├── pron_http.py
│   │   │   │   ├── sqlite_progress.py
│   │   │   │   └── markdown_notes.py
│   │   │   ├── realtime/
│   │   │   │   ├── protocol.py  # (de)serialisation of WS frames using vt_contracts
│   │   │   │   ├── session.py   # per-connection state machine
│   │   │   │   ├── vad.py       # Silero VAD (ONNX) wrapper
│   │   │   │   ├── audio.py     # resampling, PCM16 ↔ float32, framing
│   │   │   │   └── pipeline.py  # STT → teacher → TTS with cancellation
│   │   │   ├── teacher/
│   │   │   │   ├── prompts/     # versioned prompt templates (.md)
│   │   │   │   ├── conversation.py
│   │   │   │   ├── corrections.py   # structured-output parsing & validation
│   │   │   │   └── drills.py        # sentence selection by weak phonemes
│   │   │   └── http/            # routers: health, sessions, notes, progress, ws
│   │   └── tests/
│   │       ├── unit/
│   │       ├── integration/     # WS end-to-end with fake adapters
│   │       └── fixtures/audio/  # short WAV clips with expected outputs
│   └── pron/
│       ├── Dockerfile
│       ├── pyproject.toml
│       ├── src/vt_pron/
│       │   ├── __main__.py      # `vt-pron`: uvicorn configured from Settings
│       │   ├── config.py        # Settings (prefix VT_PRON_)
│       │   ├── app.py           # FastAPI app: /v1/score, /healthz
│       │   ├── g2p.py           # text → reference phonemes (IPA)
│       │   ├── recognizer.py    # wav2vec2 CTC phoneme model (typed tensors)
│       │   ├── alignment.py     # reference ↔ recognised alignment
│       │   └── scoring.py       # verdicts + confidence per phoneme
│       └── tests/
├── apps/
│   └── desktop/                 # Vite + React + TypeScript UI, wrapped by Tauri 2
│       ├── package.json
│       ├── app-icon.svg         # source for `tauri icon`
│       ├── eslint.config.ts / vite.config.ts / tsconfig*.json
│       ├── src/
│       │   ├── app/             # routing, layout, theme (follows OS light/dark)
│       │   ├── features/
│       │   │   ├── conversation/# talk screen, live transcript, corrections
│       │   │   ├── drills/      # pronunciation practice with phoneme highlighting
│       │   │   ├── notes/       # Markdown notes list + viewer
│       │   │   ├── progress/    # charts, weak phonemes, streak
│       │   │   └── settings/    # backend URL, devices, voice
│       │   ├── lib/
│       │   │   ├── ws/          # typed WS client (uses generated types)
│       │   │   ├── audio/
│       │   │   │   ├── source.ts          # AudioSource interface
│       │   │   │   ├── webAudioSource.ts  # getUserMedia + AudioWorklet (browser, WebView2, WebKitGTK)
│       │   │   │   ├── nativeSource.ts    # Tauri events from Rust capture (fallback)
│       │   │   │   └── player.ts          # 24 kHz PCM playback queue, barge-in stop
│       │   │   └── platform.ts  # isTauri(), backend URL resolution
│       │   └── generated/       # TS types from JSON Schema (do not edit)
│       ├── src-tauri/           # Rust: Tauri 2 app
│       │   ├── Cargo.toml
│       │   ├── tauri.conf.json
│       │   ├── capabilities/    # Tauri permission manifests (least privilege: main.json grants nothing yet)
│       │   └── src/
│       │       ├── main.rs
│       │       ├── lib.rs
│       │       ├── permissions.rs   # mic permission policy (on_permission_request) + WebKitGTK media stream
│       │       └── audio.rs         # optional native capture (cpal) → PCM16 events
│       └── tests/
├── eval/
│   ├── README.md
│   ├── run_pron_eval.py         # L2-ARCTIC mispronunciation detection
│   ├── run_latency_eval.py
│   └── results/latest.json
├── scripts/
│   ├── gen_ts_types.py          # contracts → JSON Schema → apps/desktop/src/generated
│   └── render_results.py        # results JSON → README table
└── data/                        # runtime bind mount (gitignored): notes/, progress.db. Model caches use Docker named volumes
```

## Realtime protocol (`/ws/session`)

One WebSocket per conversation. **Binary frames carry audio; text frames carry JSON events.** Every JSON event has `type` and `v` (protocol version).

**Audio formats**
- Client → server: PCM16 little-endian, mono, **16 kHz**, 20 ms frames (640 bytes).
- Server → client: PCM16 little-endian, mono, **24 kHz** (Kokoro's native rate), chunked as produced.

**Client → server events**

| `type` | Payload | Meaning |
|---|---|---|
| `session.start` | `mode` (`conversation` \| `drill`), `level`, `topic?` | Begin a session |
| `input.commit` | — | Push-to-talk released (manual end of turn) |
| `input.interrupt` | — | User started speaking while the teacher talks |
| `drill.next` | `phonemes?` | Ask for the next drill sentence |
| `session.end` | — | Finish; triggers note generation |

**Server → client events**

| `type` | Payload | Meaning |
|---|---|---|
| `vad.speech_started` / `vad.speech_stopped` | `t_ms` | Voice activity |
| `transcript.final` | `text`, `turn_id` | What the user said |
| `assistant.text.delta` | `text`, `turn_id` | Streaming teacher text |
| `assistant.audio.started` / `assistant.audio.finished` | `turn_id`, `sample_rate` | Bracket the binary TTS frames |
| `correction` | list of `{original, suggestion, kind, explanation}` | Grammar/wording feedback |
| `drill.sentence` | `text`, `ipa`, `target_phonemes` | Sentence to read |
| `pron.result` | per-phoneme verdicts + overall score | Pronunciation feedback |
| `note.ready` | `note_id` | Session note written |
| `error` | `code`, `message`, `retryable` | Recoverable or fatal error |

### Turn lifecycle

```
user speaks ──► VAD start ──► frames buffered ──► VAD stop (or input.commit)
     ──► STT ──► transcript.final
     ──► teacher (LLM, streamed) ──► sentence splitter ──► TTS per sentence ──► audio frames
     └── in parallel (drill mode): pron.score(audio, target) ──► pron.result
barge-in: VAD start during playback ──► cancel LLM + TTS tasks ──► new user turn
```

Text is sent to TTS **sentence by sentence** as the LLM streams, so audio starts before the full reply is generated.

## Pronunciation scoring (`pron`)

1. **G2P**: target sentence → reference phonemes (IPA) with a pronunciation dictionary and a G2P fallback for unknown words.
2. **Recognition**: wav2vec2 CTC phoneme model → per-frame phoneme posteriors.
3. **Alignment**: align recognised phonemes to the reference (edit-distance alignment over phonemes, refined with CTC forced alignment for timings).
4. **Scoring**: each reference phoneme gets `correct | mispronounced | missing`, plus `extra` insertions and a goodness-of-pronunciation-style confidence.

Tensor shapes are typed with `jaxtyping` and checked at runtime in tests (`beartype`), e.g. `Float[Tensor, "frames vocab"]`.

## Persistence

- **SQLite** (`data/progress.db`) for sessions, turns, corrections and phoneme stats. It is a single-user app, so SQLite is the right tool: zero ops and trivially backed up.
- **Markdown notes** (`data/notes/*.md`) with YAML front matter, one per session, plus a generated `progress.md`. They are human-readable, Obsidian-compatible, and rendered in the UI with `react-markdown` + `remark-gfm` + `rehype-sanitize` (sanitised: notes include model output).

## Architecture decisions (summary)

| # | Decision | Why | Alternative rejected |
|---|---|---|---|
| 1 | Audio is captured by the UI (webview/browser), never inside containers | Echo cancellation and noise suppression built in; Docker on Windows/macOS cannot reach the mic reliably | Native audio (PortAudio) inside containers |
| 1b | **Tauri 2 + React** desktop shell; the same UI also runs in a browser | Native window and installers on Windows/Linux with a small footprint; one UI codebase for desktop and home lab. **Linux caveat:** WebKitGTK silently denies `getUserMedia` unless the app answers the permission request, so `permissions.rs` registers Tauri's cross-platform `Builder::on_permission_request` (Tauri ≥ 2.12) to allow the **microphone only, for the app's own origins only** (bundled UI; dev server in debug builds), and enables WebKitGTK's `enable-media-stream` setting. Fallback: native capture with `cpal` behind the same `AudioSource` interface | Electron (heavier), native toolkits (two UIs) |
| 2 | Hand-written FastAPI WebSocket pipeline | Learning goal; full control over cancellation and latency | Pipecat / LiveKit Agents (good options; may be revisited) |
| 3 | OpenAI-compatible interfaces everywhere | One adapter covers Ollama, llama.cpp, LM Studio, Speaches, Kokoro and cloud | Vendor SDKs per backend |
| 4 | Separate `pron` service | Heavy ML deps (torch) isolated from the API; scalable and testable on its own | Scoring inside `api` |
| 5 | SQLite + Markdown | Single user, zero ops, human-readable notes | Postgres |
| 6 | uv workspace monorepo (+ pnpm workspace for the UI) | One lockfile per ecosystem, shared tooling, fast installs | Poetry / separate repos |
| 7 | `just` as the task runner | Runs natively on Windows (PowerShell) as well as Linux/macOS; installs without admin rights (`uv tool install rust-just`) | Make (no native Windows), npm scripts (Node-only) |
