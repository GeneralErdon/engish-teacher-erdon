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
| `ui` | this repo | React + TypeScript: mic capture (AudioWorklet), voice activity detection for call mode (Silero VAD on ONNX Runtime Web), playback, conversation, Markdown notes viewer, progress. Runs inside `desktop` **and** in a plain browser (served by `api`) | WebSocket + REST to `api` |
| `api` | this repo | Realtime session (turns, streamed replies and voice, cancellation), teacher logic, notes, progress, persistence | FastAPI: REST + `/ws/session` |
| `pron` | this repo | Pronunciation scoring: G2P → phoneme recognition → alignment → per-phoneme verdicts | REST `POST /v1/score` |
| `stt` | third party | Speech-to-text (Speaches/faster-whisper or whisper.cpp) | OpenAI `/v1/audio/transcriptions` (or whisper.cpp `/inference` via adapter) |
| `llm` | third party | Chat model: Ollama (local or cloud), llama.cpp server, LM Studio, OpenAI, Anthropic, Gemini, or any compatible server. Chosen in the UI (`/v1/llm/*`) or with `VT_LLM_*` | OpenAI `/v1/chat/completions` or Anthropic `/v1/messages` (streaming) |
| `tts` | third party | Text-to-speech: Kokoro on ONNX Runtime, served by the same Speaches as `stt` (Kokoro-FastAPI also works) | OpenAI `/v1/audio/speech` (streaming PCM, 24 kHz) |

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
│       ├── apps.yml             # installers + APK: by hand, or called by release.yml
│       └── release.yml          # every merge into master: GitHub release + images to GHCR
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
│   │   │   ├── openapi.py       # `vt-api-openapi`: write the OpenAPI schema without a server
│   │   │   ├── main.py          # app factory, lifespan, router wiring, UI static files
│   │   │   ├── config.py        # Settings (pydantic-settings)
│   │   │   ├── container.py     # dependency wiring: ports → adapters
│   │   │   ├── domain/          # entities & value objects (Session, Turn, Correction, PhonemeScore…)
│   │   │   ├── ports/           # Protocols: SpeechToText, ChatModel, TextToSpeech,
│   │   │   │                    #            PronunciationScorer, NotesRepository, ProgressRepository
│   │   │   ├── services/        # use cases over the ports, called by http/ (llm.py: provider settings)
│   │   │   ├── adapters/
│   │   │   │   ├── openai_models.py # is a speech server up, with our model downloaded?
│   │   │   │   ├── openai_stt.py
│   │   │   │   ├── whispercpp_stt.py
│   │   │   │   ├── openai_chat.py   # Chat Completions: OpenAI, Gemini, Ollama, llama.cpp, LM Studio...
│   │   │   │   ├── anthropic_chat.py# Messages API: Anthropic and compatible servers
│   │   │   │   ├── chat_factory.py  # provider settings → the right chat adapter
│   │   │   │   ├── secret_key.py    # master key: VT_SECRET_KEY, key file or OS keyring
│   │   │   │   ├── secret_box.py    # HKDF subkeys + AES-256-GCM for secret columns
│   │   │   │   ├── sql/             # SQLCipher database (SQLAlchemy), repositories, Alembic migrations
│   │   │   │   ├── openai_tts.py
│   │   │   │   ├── pron_http.py
│   │   │   │   ├── sqlite_progress.py
│   │   │   │   └── markdown_notes.py
│   │   │   ├── realtime/
│   │   │   │   ├── protocol.py  # (de)serialisation of WS frames using vt_contracts
│   │   │   │   ├── session.py   # per-connection conversation: turns, streamed replies, voice, corrections, barge-in
│   │   │   │   ├── sentences.py # streamed reply → sentences for text-to-speech
│   │   │   │   ├── audio.py     # resampling, PCM16 ↔ float32, framing
│   │   │   │   └── pipeline.py  # STT → teacher → TTS with cancellation
│   │   │   ├── teacher/
│   │   │   │   ├── prompts.py   # prompt templates (string.Template), reviewed like code
│   │   │   │   ├── conversation.py
│   │   │   │   ├── corrections.py   # structured-output parsing & validation
│   │   │   │   └── drills.py        # sentence selection by weak phonemes
│   │   │   └── http/            # routers: health, llm, learner, speech, ws, sessions, notes, progress; schema.py adds WS events to OpenAPI
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
│       ├── components.json      # shadcn/ui CLI settings
│       ├── openapi.json         # the api's OpenAPI schema (`just types`; CI checks it is current)
│       ├── public/pcm-recorder.worklet.js # audio thread: mic → PCM16 16 kHz frames (resamples itself)
│       ├── src/
│       │   ├── styles.css       # Tailwind 4 + design tokens (OKLCH, light/dark)
│       │   ├── app/             # providers, router (hash history), query client, motion features
│       │   ├── routes/          # file-based routes: __root (app shell), index (Home), settings
│       │   ├── components/
│       │   │   ├── ui/          # shadcn/ui components (Radix), owned and edited here
│       │   │   └── layout/      # sidebar (desktop) and tab bar (phone), animated highlight
│       │   ├── features/
│       │   │   ├── home/        # welcome + status of the backend and the model
│       │   │   ├── status/      # api health polling
│       │   │   ├── conversation/# talk screen, live transcript, corrections
│       │   │   ├── drills/      # pronunciation practice with phoneme highlighting
│       │   │   ├── notes/       # Markdown notes list + viewer
│       │   │   ├── progress/    # charts, weak phonemes, streak
│       │   │   └── settings/    # language model (providers, keys, test), appearance, backend
│       │   ├── lib/
│       │   │   ├── api/         # openapi-fetch client + typed TanStack Query hooks, ApiError
│       │   │   ├── theme.ts     # system / light / dark, stored per device
│       │   │   ├── ws/          # typed WS client (uses generated types)
│       │   │   ├── audio/
│       │   │   │   ├── source.ts          # AudioSource interface, level meter, mic error messages
│       │   │   │   ├── web-audio-source.ts # getUserMedia + AudioWorklet (browser, WebView2, WebKitGTK)
│       │   │   │   ├── vad.ts             # call mode: Silero VAD (vad-web), utterances as PCM16 frames
│       │   │   │   ├── nativeSource.ts    # Tauri events from Rust capture (fallback)
│       │   │   │   └── player.ts          # 24 kHz PCM playback queue, output level, barge-in stop
│       │   │   └── platform.ts  # isTauri(), backend URL resolution
│       │   └── generated/       # api.d.ts (from openapi.json) and routeTree.gen.ts (do not edit)
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
│   ├── gen_ts_types.py          # WS event types (OpenAPI does not describe WebSocket messages)
│   └── render_results.py        # results JSON → README table
└── data/                        # runtime bind mount (gitignored): voice-tutor.db (encrypted), notes/. Model caches use Docker named volumes
```

## Realtime protocol (`/ws/session`)

One WebSocket per conversation. **Binary frames carry audio; text frames carry JSON events.** Every JSON event has `type` and `v` (protocol version). The events are Pydantic models in `vt_contracts.ws`; they are added to the OpenAPI document (which cannot describe WebSockets), so the UI gets generated TypeScript types for them too.

**Origin check.** Browsers apply no CORS to WebSockets: any page could open this socket and spend the learner's API credits. The api accepts only `VT_CORS_ORIGINS`, the page it serves itself, and clients that send no `Origin` (not browsers); others are closed with code 1008.

Implemented so far: `session.start` (with `speak`), `session.update`, `input.text`, binary audio + `input.commit` (push-to-talk), `input.interrupt`, `session.end` → `session.ready`, `transcript.final`, `assistant.text.delta`/`done`, `assistant.audio.started` + binary audio + `assistant.audio.done`, `correction`, `turn.metrics`, `error`. Drills follow.

**Call mode (hands-free).** Voice activity detection runs in the UI, not in the api: Silero VAD v5 on ONNX Runtime Web (`@ricky0123/vad-web`), loaded only when a call starts (the model, worklet and WebAssembly runtime are served from `/vad/` by the app itself, ~17 MB, no CDN). When the learner stops talking (900 ms of silence), the UI sends the utterance as PCM16 frames and `input.commit`, exactly like push-to-talk, so the protocol did not change. Barge-in happens where the audio plays: speech confirmed during the tutor's voice (400 ms over the threshold) stops the playback at once and sends `input.interrupt`. While the tutor speaks, the threshold goes up (0.5 → 0.8), so its own voice leaking from the speakers into the microphone does not count as the learner's; echo cancellation does the rest. The `vad.*` events below are therefore not used.

**The tutor's voice.** With `speak`, the session cuts the streamed reply into sentences (`realtime/sentences.py`: terminal punctuation followed by whitespace, a few abbreviations kept whole, Markdown and emoji removed) and synthesises them one at a time, in order, while the model keeps writing. Audio frames go out as Speaches produces them, bracketed by `assistant.audio.started` and `assistant.audio.done`; the UI schedules them back to back in one `AudioContext` (`lib/audio/player.ts`). An interruption cancels the reply task, which cancels the voice task with it, and the UI drops any frames of that turn still in flight. If the voice fails, the reply goes on as text with a `tts_failed` error.

**Microphone capture.** The AudioContext runs at the device rate and the worklet averages the samples that fall in each 16 kHz output sample: Firefox and WebKit refuse to connect a microphone to a context at another rate, so asking the browser to resample is not portable. The api buffers up to the longest turn set in **Settings → Voice** (`VT_MAX_TURN_S` until one is saved, 120 s by default) and keeps a longer turn's first part, marking its transcript as cut; it rejects clips under 0.3 s, and transcribes on `input.commit`.

**Audio formats**
- Client → server: PCM16 little-endian, mono, **16 kHz**, 20 ms frames (640 bytes).
- Server → client: PCM16 little-endian, mono, **24 kHz** (Kokoro's native rate), chunked as produced.

**Client → server events**

| `type` | Payload | Meaning |
|---|---|---|
| `session.start` | `topic?`, `speak` (level and explanation language come from the learner profile, `/v1/learner`) | Begin a session; `speak` makes the tutor read its replies aloud |
| `session.update` | `speak` | Voice on or off, from the next reply |
| `input.text` | `text` | A typed message (same pipeline as a spoken one, without STT) |
| `input.commit` | — | Push-to-talk released: transcribe the binary frames received since the last turn |
| `input.interrupt` | — | User started speaking while the teacher talks |
| `drill.next` | `phonemes?` | Ask for the next drill sentence |
| `session.end` | — | Finish; triggers note generation |

**Server → client events**

| `type` | Payload | Meaning |
|---|---|---|
| `session.ready` | `level`, `provider`, `model` | Session started; which model answers |
| `vad.speech_started` / `vad.speech_stopped` | `t_ms` | Voice activity |
| `transcript.final` | `text`, `turn_id`, `source` (`text` \| `voice`), `stt_ms` | What the user said or typed; `stt_ms` is the transcription time |
| `assistant.text.delta` | `text`, `turn_id` | Streaming teacher text |
| `assistant.text.done` | `text`, `turn_id`, `interrupted` | The whole reply (what was sent, if interrupted) |
| `turn.metrics` | `turn_id`, `first_token_ms`, `reply_ms`, `first_audio_ms` | Reply latency (Phase 0 measurements), sent once the reply and its audio are complete. Voice to voice = `stt_ms + first_audio_ms` |
| `assistant.audio.started` / `assistant.audio.done` | `turn_id`, `sample_rate` / `turn_id`, `interrupted` | Bracket the binary TTS frames of one reply |
| `correction` | `turn_id`, `corrected`, `items: [{original, suggestion, kind, explanation}]`, `latency_ms` | Feedback on the learner's message, computed **in parallel with the reply** (a second LLM call, JSON validated); the UI diffs `corrected` against the message, Tandem-style. A new message interrupts the reply but not the previous correction |
| `drill.sentence` | `text`, `ipa`, `target_phonemes` | Sentence to read |
| `pron.result` | per-phoneme verdicts + overall score | Pronunciation feedback |
| `note.ready` | `note_id` | Session note written |
| `error` | `code`, `message`, `retryable` | Recoverable or fatal error |

### Turn lifecycle

```
user speaks ──► (call mode: VAD in the UI) ──► frames ──► input.commit (VAD end, or push-to-talk)
     ──► STT ──► transcript.final
     ──► teacher (LLM, streamed) ──► sentence splitter ──► TTS per sentence ──► audio frames
     └── in parallel (drill mode): pron.score(audio, target) ──► pron.result
barge-in: speech during playback ──► UI stops the audio + input.interrupt ──► cancel LLM + TTS tasks ──► new user turn
```

Text is sent to TTS **sentence by sentence** as the LLM streams, so audio starts before the full reply is generated.

## Pronunciation scoring (`pron`)

1. **G2P**: target sentence → reference phonemes (IPA) with a pronunciation dictionary and a G2P fallback for unknown words.
2. **Recognition**: wav2vec2 CTC phoneme model → per-frame phoneme posteriors.
3. **Alignment**: align recognised phonemes to the reference (edit-distance alignment over phonemes, refined with CTC forced alignment for timings).
4. **Scoring**: each reference phoneme gets `correct | mispronounced | missing`, plus `extra` insertions and a goodness-of-pronunciation-style confidence.

Tensor shapes are typed with `jaxtyping` and checked at runtime in tests (`beartype`), e.g. `Float[Tensor, "frames vocab"]`.

## Persistence

- **SQLite, encrypted** (`data/voice-tutor.db`): today the settings saved from the UI (chat model providers with their API keys, learner profile); later sessions, turns, corrections and phoneme stats. It is a single-user app, so SQLite is the right tool: zero ops and trivially backed up. SQLCipher encrypts the file and API keys are sealed again per column, with a master key kept out of the database, in the OS keyring when there is one ([configuration.md#encryption](configuration.md#encryption)).
- **SQLAlchemy 2 + Alembic.** Tables in portable SQL and migrations applied at startup, so Postgres can be added as a second engine without touching the repositories. Queries are synchronous and run in worker threads: a few per minute do not need an async driver, and one code path serves both engines.
- **Markdown notes** (`data/notes/*.md`) with YAML front matter, one per session, plus a generated `progress.md`. They are human-readable, Obsidian-compatible, and rendered in the UI with `react-markdown` + `remark-gfm` + `rehype-sanitize` (sanitised: notes include model output).

## Distribution

The same code ships in two forms. Only *who starts the processes* changes: the api reaches every model through a URL from its settings and never assumes Docker.

| Form | For | What runs where | Status |
|---|---|---|---|
| **Server** (Docker Compose) | Self-hosters, home labs, a GPU machine serving other devices | `api`, `pron` and the model servers in containers, hardware picked with `--profile`. The UI is served by the api (browser, phone over HTTPS) or used through the desktop app as a client | Phase 1 |
| **Desktop client** | Anyone with a server already running | The installer contains only the Tauri window and the UI; it connects to a server | Today (installers from Phase 3) |
| **Desktop all-in-one** | Learners who should never see Docker or a terminal | The app starts the model servers and the api as **Tauri sidecars**, downloads the models on first run with a progress bar, and stops everything on exit | Phase 4 |

**Why both.** Docker solves the hardware matrix (CPU, CUDA, ROCm, Vulkan) and the home-lab case, but asks a learner to install Docker. On Windows that also means WSL2. Desktop AI apps that "just work" bundle their engines instead: Jan (Tauri) and LM Studio ship llama.cpp and download models in-app; AnythingLLM publishes Desktop and Docker editions of one codebase. The all-in-one form also fixes the two cases Docker handles worst: **macOS** (no GPU in Docker, so Metal only works natively) and **Windows with an AMD GPU**.

**Rules this sets for earlier phases**, so Phase 4 stays packaging work and not a rewrite:
- Prefer components that ship as native binaries or run on ONNX Runtime: llama.cpp and whisper.cpp (one Vulkan build covers AMD, NVIDIA and Intel), Kokoro ONNX, and the wav2vec2 phoneme model exported to ONNX. Torch may be used to export or evaluate models, not at runtime.
- Every model endpoint and data path comes from `Settings`; nothing in the api assumes container hostnames or `/data`.
- The desktop app talks to its backend through one configurable URL, so "client of a server" and "all-in-one" are the same UI.

**Not doing:** a button that runs `docker compose` from the app. It still requires Docker (and WSL2 on Windows), which is the barrier the all-in-one form removes.

## Architecture decisions (summary)

| # | Decision | Why | Alternative rejected |
|---|---|---|---|
| 1 | Audio is captured by the UI (webview/browser), never inside containers | Echo cancellation and noise suppression built in; Docker on Windows/macOS cannot reach the mic reliably | Native audio (PortAudio) inside containers |
| 1b | **Tauri 2 + React** desktop shell; the same UI also runs in a browser | Native window and installers on Windows/Linux with a small footprint; one UI codebase for desktop and home lab. **Linux caveat:** WebKitGTK silently denies `getUserMedia` unless the app answers the permission request, so `permissions.rs` registers Tauri's cross-platform `Builder::on_permission_request` (Tauri ≥ 2.12) to allow the **microphone only, for the app's own origins only** (bundled UI; dev server in debug builds), and enables WebKitGTK's `enable-media-stream` setting. Fallback: native capture with `cpal` behind the same `AudioSource` interface | Electron (heavier), native toolkits (two UIs) |
| 2 | Hand-written FastAPI WebSocket pipeline | Learning goal; full control over cancellation and latency | Pipecat / LiveKit Agents (good options; may be revisited) |
| 3 | Standard wire protocols, not vendors: OpenAI-compatible everywhere, plus the Anthropic Messages API for chat. Each protocol through its official SDK (`openai`, `anthropic`, both on httpx2) | Two chat adapters cover Ollama (local and cloud), OpenAI, Gemini, llama.cpp, LM Studio, Anthropic and any compatible server; the same OpenAI-compatible approach covers Speaches and Kokoro. The SDKs bring streaming, retries and typed errors | One SDK per vendor; hand-written HTTP clients |
| 4 | Separate `pron` service | Heavy ML deps (torch) isolated from the API; scalable and testable on its own | Scoring inside `api` |
| 5 | SQLite (encrypted with SQLCipher, API keys sealed again per column) + Markdown | Single user, zero ops, human-readable notes; saved API keys and, later, conversations unreadable without the master key, which lives in the OS keyring | Postgres (planned as an option for servers), plain JSON files |
| 6 | uv workspace monorepo (+ pnpm workspace for the UI) | One lockfile per ecosystem, shared tooling, fast installs | Poetry / separate repos |
| 7 | `just` as the task runner | Runs natively on Windows (PowerShell) as well as Linux/macOS; installs without admin rights (`uv tool install rust-just`) | Make (no native Windows), npm scripts (Node-only) |
| 8 | Two distributions of one codebase: Docker Compose (server) and, from Phase 4, a desktop installer that runs the backend as Tauri sidecars ([Distribution](#distribution)) | One-click install for learners; Docker keeps hardware profiles and the home-lab case; Vulkan builds cover every GPU vendor without per-vendor images; native Metal on macOS | Desktop-only bundle (loses the home-lab case), Docker-only (too hard for learners), the app driving `docker compose` (still needs Docker) |
| 9 | UI: TanStack Router (file routes, code split per page) + TanStack Query over a client generated from the api's OpenAPI schema (`openapi-fetch` + `openapi-react-query`); react-hook-form + zod; shadcn/ui (Radix) + Tailwind 4; `motion` loaded lazily (`LazyMotion`) | One source of truth for API types, from the Pydantic models to the hooks; accessible primitives without a component library to fight; animations that cost nothing until first paint and respect reduced motion | Hand-written fetch types, Redux, MUI/Chakra, CSS-in-JS |
| 10 | Voice activity detection in the UI (Silero VAD on ONNX Runtime Web), not in the api | Barge-in where the audio plays, with no network round trip; the UI knows when the tutor is audible and makes detection stricter then; the protocol stays push-to-talk's (frames + `input.commit`), so the api needs no model and only receives speech | Silero in the api (continuous upstream audio, barge-in one round trip later, a model to download on the server) |
| 11 | The api owns speech model files; Speaches only serves them | Settings → Voice needs progress, cancel and uninstall from the UI, so the api downloads into a Hugging Face cache folder that Speaches mounts (`data/models`); Phase 4's first-run model download reuses the same manager | Speaches' own download endpoint (no progress, no cancel) |
