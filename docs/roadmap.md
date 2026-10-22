# Roadmap

Each phase ends with something usable and measured. Time boxes are deliberate: if a phase overruns by more than 50 %, stop and re-scope.

## Phase -1: Repository bootstrap
- [x] Local git repo (no remote yet), tooling, workspace layout, CI files, hello-world services with passing tests (2026-10-20)
- [ ] Tauri 2 + React app opens a native window on Linux and Windows. **Linux done** (Fedora 44, WebKitGTK 2.54, shows the api `/healthz`); Windows pending a manual run (CI already compiles, lints and tests the Rust shell on Windows)

## Phase 0: Spike (≤ 5 h)
- [ ] Mic capture inside Tauri on **Linux (WebKitGTK)** and **Windows (WebView2)**. Go/no-go for `getUserMedia`; otherwise native `cpal` fallback
- [ ] Silero VAD + Speaches + llama.cpp (Vulkan) + Kokoro wired in a throwaway script on the reference machine
- [ ] Measure voice-to-voice latency. **Go if p50 < 1.5 s**
- [ ] `pronounce-assess` / wav2vec2 phoneme model on 10 self-recorded sentences, compared with a commercial app. **Go if obvious errors are detected**

## Phase 1: Conversation MVP (≈ 20–25 h)
- [ ] (done in bootstrap) uv workspace, tooling, pre-commit, CI skeleton
- [ ] `vt_contracts` WS protocol + generated TS types
- [ ] `api`: settings, container, ports, OpenAI-compatible adapters, health checks
- [ ] Chat model providers chosen from the UI: Ollama (local and cloud), OpenAI, Anthropic, Gemini, and any OpenAI- or Anthropic-compatible endpoint. API keys stay in the api and never come back to the UI
- [ ] UI shell: responsive navigation, Home (welcome + status), Settings, light/dark theme, typed API client generated from the api's OpenAPI schema
- [ ] Desktop: configurable backend URL (for a home-lab server) and a "backend unavailable" screen with the next step to take
- [ ] Realtime session: VAD, turn-taking, sentence-streamed TTS, barge-in cancellation
- [ ] Teacher: level-aware conversation + structured corrections
- [ ] UI (desktop + browser): talk screen, live transcript, corrections panel
- [ ] Session note (Markdown) + notes viewer
- [ ] `compose.yaml` with `cpu`, `amd`, `external` profiles; README quick start verified on a clean machine

## Phase 2: Pronunciation (≈ 15–20 h)
- [ ] `pron` service: G2P, recognizer, alignment, scoring (typed tensors)
- [ ] Drill mode in `api` and the UI with phoneme highlighting
- [ ] Drill selection from weakest phonemes
- [ ] `just eval-pron` on L2-ARCTIC; results in README

## Phase 3: Polish (≈ 8–12 h)
- [ ] Progress dashboard (weak phonemes, recurring mistakes, streak)
- [ ] `nvidia` profile, HTTPS profile (Caddy), Tailscale docs
- [ ] Multi-arch images on GHCR; desktop installers (Windows + Linux) built in CI; release workflow
- [ ] Demo video (2 min) and write-up
- [ ] Choose licence (MIT planned)

## Phase 4: One-click desktop install, no Docker (≈ 20–30 h)
Goal: download the installer, open it, talk. Docker Compose stays as the server and home-lab install; both run the same code ([architecture.md#distribution](architecture.md#distribution)).
- [ ] Tauri sidecars started and stopped by the app: `llama-server` and the whisper.cpp server (Vulkan builds cover AMD, NVIDIA and Intel GPUs on Linux and Windows; Metal on macOS), and the api as a self-contained executable
- [ ] First-run setup screen: hardware detection, model choice by available VRAM/RAM, model download with progress, disk-space check
- [ ] Pronunciation and TTS on ONNX Runtime, so no torch at runtime: wav2vec2 phoneme model exported to ONNX, Kokoro ONNX
- [ ] Installers built in CI for Windows, Linux and macOS. Code signing (Windows) and notarization (macOS) when there is a budget for certificates
- [ ] Measure: installer size, first-run time to first conversation, idle RAM. Stop and re-scope if the installer passes ~400 MB without models

## Later / maybe
- Python 3.15 once torch, onnxruntime and ctranslate2 publish cp315 wheels (one-line change: `.python-version` + `requires-python`)
- TypeScript 7 (native compiler) once `typescript-eslint` supports it; Node 26 LTS (2026-10-28) when convenient
- Try Astral's `ty` as the type checker once it leaves beta
- Pipecat or WebRTC transport as an alternative to the hand-written WebSocket
- Wake word ("hey tutor") with a local model
- More learner L1s
