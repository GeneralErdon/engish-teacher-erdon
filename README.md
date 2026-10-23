# voice-tutor

[![CI](https://github.com/GeneralErdon/engish-teacher-erdon/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/GeneralErdon/engish-teacher-erdon/actions/workflows/ci.yml)
[![CodeQL](https://github.com/GeneralErdon/engish-teacher-erdon/actions/workflows/codeql.yml/badge.svg?branch=develop)](https://github.com/GeneralErdon/engish-teacher-erdon/actions/workflows/codeql.yml)
[![Security](https://github.com/GeneralErdon/engish-teacher-erdon/actions/workflows/security.yml/badge.svg?branch=develop)](https://github.com/GeneralErdon/engish-teacher-erdon/actions/workflows/security.yml)
[![codecov](https://codecov.io/gh/GeneralErdon/engish-teacher-erdon/branch/develop/graph/badge.svg)](https://codecov.io/gh/GeneralErdon/engish-teacher-erdon)
![coverage floor](https://img.shields.io/badge/coverage%20floor-97%25-brightgreen)
![Python 3.14](https://img.shields.io/badge/python-3.14-3776AB?logo=python&logoColor=white)
![Tauri 2](https://img.shields.io/badge/tauri-2-24C8DB?logo=tauri&logoColor=white)

> A private, self-hosted **English speaking coach**. Talk to it by voice, get grammar corrections, and practise pronunciation with **phoneme-level feedback**, all on your own machine.

Your audio never leaves your computer. No accounts, no telemetry, no subscriptions.

> [!IMPORTANT]
> **Early development.** The repository bootstrap (Phase -1) is done: the services, the desktop shell, Docker, CI and tooling all run, but the voice features below are the target, not yet built. Voice conversation lands in Phase 1. Track progress in [docs/roadmap.md](docs/roadmap.md).
>
> **What runs today:** the `api` and `pron` services (health endpoints), all model containers, and the UI (desktop window or browser) showing the backend status.

---

## Contents

- [Features](#features) · [How it works](#how-it-works)
- [Requirements](#requirements)
- [Run it with Docker](#run-it-with-docker)
- [Run it locally (development)](#run-it-locally-development)
- [Desktop app and installers](#desktop-app-and-installers)
- [Configuration](#configuration) · [Hardware profiles](#pick-a-hardware-profile) · [Remote access](#using-it-from-another-device-phone-home-lab)
- [Commands](#commands) · [Project layout](#project-layout) · [Troubleshooting](#troubleshooting)
- [Results](#results) · [Limitations](#honest-limitations) · [Privacy](#privacy) · [License](#license)

## Features

Planned scope (see [Status](#voice-tutor) above):

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
   │  mic capture · voice activity detection (call mode) · playback · Markdown notes · progress
   │  WebSocket: binary PCM16 audio + typed JSON events
   ▼
api (FastAPI) ── turns · streamed replies and voice · barge-in · teacher logic · notes · progress (SQLite)
   ├─► stt   speech-to-text   (Speaches / faster-whisper, or whisper.cpp)
   ├─► llm   chat model       (Ollama, llama.cpp server, LM Studio, or any OpenAI-compatible API)
   ├─► tts   text-to-speech   (Kokoro, served by the same Speaches)
   └─► pron  pronunciation scoring (wav2vec2 phoneme recognition + alignment) — this repo
```

It is a monorepo: the Python services live in a [uv](https://docs.astral.sh/uv/) workspace (`services/api`, `services/pron`, shared `packages/contracts`), and the UI and desktop shell in a [pnpm](https://pnpm.io/) workspace (`apps/desktop`). Details: [docs/architecture.md](docs/architecture.md).

## Requirements

**To run it** (backend + browser UI), you only need:

- **Docker** Engine 25+ or Docker Desktop, with **Compose v2.30+** (`docker compose version`)
- ~10 GB of free disk for images and models, and a microphone

**To develop it or build the desktop app**, you also need the toolchain below. The versions are pinned in the repository, so the tools pick them up automatically:

| Tool | Version | Pinned in | Used for |
|---|---|---|---|
| [uv](https://docs.astral.sh/uv/) | ≥ 0.13 | `pyproject.toml` (`required-version`) | Python versions, virtualenv, dependencies, lockfile |
| Python | 3.14 | `.python-version` (uv installs it for you) | `api`, `pron`, `contracts` |
| [just](https://just.systems) | ≥ 1.47 | — | Task runner (the `justfile`), same commands on every OS |
| Node.js | 24 LTS | `.nvmrc` | UI tooling |
| [pnpm](https://pnpm.io/) | 12 | `package.json` (`packageManager`; pnpm switches itself to it) | UI dependencies |
| Rust | 1.99.1 | `rust-toolchain.toml` (rustup installs it for you) | Tauri desktop shell |
| Tauri system libraries | — | — | WebKitGTK on Linux, WebView2 on Windows |
| Docker | as above | — | Model services during development |

Why Python 3.14 and not 3.15: the pronunciation stack needs torch, onnxruntime and ctranslate2 wheels, which do not exist for 3.15 yet. See [docs/development.md](docs/development.md#toolchain) for every version decision.

### Install the toolchain

<details open>
<summary><b>Linux (Fedora)</b></summary>

```bash
# uv and just (user-level, no sudo)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install rust-just

# Rust (user-level; rust-toolchain.toml selects the exact version)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Node 24 (any version manager works; nvm shown) and pnpm
nvm install 24 && npm install -g pnpm

# Tauri 2 system dependencies
sudo dnf install webkit2gtk4.1-devel openssl-devel curl wget file \
  libappindicator-gtk3-devel librsvg2-devel libxdo-devel
sudo dnf group install c-development

# Docker: https://docs.docker.com/engine/install/fedora/
```

</details>

<details>
<summary><b>Linux (Debian / Ubuntu)</b></summary>

Same uv, just, Rust, Node and pnpm commands as Fedora, then:

```bash
sudo apt update
sudo apt install libwebkit2gtk-4.1-dev build-essential curl wget file \
  libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev
```

</details>

<details>
<summary><b>Windows 10/11</b></summary>

```powershell
winget install astral-sh.uv Casey.Just Rustlang.Rustup OpenJS.NodeJS.LTS pnpm.pnpm Docker.DockerDesktop
```

Also install the **Microsoft C++ Build Tools** ("Desktop development with C++"). WebView2 is preinstalled on Windows 10/11. The `justfile` runs its recipes with PowerShell.

</details>

<details>
<summary><b>macOS</b> (not tested yet)</summary>

```bash
xcode-select --install
brew install uv just rustup node@24 pnpm
rustup-init
```

Docker Desktop has no GPU access on macOS: use the `external` profile with a native Ollama / LM Studio.

</details>

## Run it with Docker

The whole stack in containers: `api` (which also serves the UI), `pron`, and the model services of your hardware profile.

```bash
git clone https://github.com/GeneralErdon/engish-teacher-erdon.git voice-tutor
cd voice-tutor
cp .env.example .env                  # pick VT_PROFILE and the models (comments explain each one)
docker compose --profile cpu up -d    # use the profile you set: cpu | nvidia | amd | external
```

Or, with `just` installed: `just up` (it reads `VT_PROFILE` from `.env`, builds and waits until every service is healthy).

Then open **http://localhost:8080**: pick a language model in **Settings**, then talk to your tutor in **Practice**. Speaking needs the one-time [voice setup](docs/configuration.md#voice-setup).

The first start downloads several GB (images, then the chat model). The `api` comes up right away; each model service turns `healthy` in `docker compose ps` once its model is ready. Follow the downloads with `docker compose logs -f`. Every port is published on `127.0.0.1` only:

| Port | Service |
|---|---|
| 8080 | `api` + UI |
| 8001 | `pron` |
| 8000 | `stt` and `tts` (Speaches: Whisper and Kokoro) |
| 8081 | `llm` (llama.cpp / Ollama) |

Stop everything with `docker compose --profile "*" down` (or `just down`). Downloaded models stay in Docker volumes for the next start.

## Run it locally (development)

```bash
git clone https://github.com/GeneralErdon/engish-teacher-erdon.git voice-tutor
cd voice-tutor
cp .env.example .env
just setup          # uv sync (all Python packages) + pnpm install + pre-commit hooks
just check          # optional: lint + type-check everything
just test           # optional: every test suite
```

Then pick how much of the stack you need:

| You want to | Run | Open |
|---|---|---|
| Work on the UI or the api, or chat by text with a cloud model | `just dev-api` and, in a second terminal, `just dev-ui` | http://localhost:1420 |
| Also talk: speak, and hear the tutor (local speech recognition and voice) | `just voice` once ([voice setup](docs/configuration.md#voice-setup)), then the above | http://localhost:1420 |
| The full loop: models in Docker, api and UI local | `just dev` | http://localhost:1420 |
| Try it on your phone (same Wi-Fi), with a cloud chat model | `just dev-phone` (= `voice`, then `dev-api` + `dev-lan`) | https://&lt;your computer's IP&gt;:1420 (accept the self-signed certificate once) |
| The desktop window | `just dev-api` (or `just models` + `just dev-api`), then `just desktop` | native window |
| Production images with rebuild on change | `just watch` | http://localhost:8080 |

- `just dev-api` runs uvicorn with auto-reload on http://localhost:8080 (API docs at `/docs`).
- `just dev-ui` runs Vite with hot reload on http://localhost:1420. It forwards `/v1`, `/healthz` and `/ws` to the api, so the page talks to one origin.
- `just dev-lan` is `dev-ui` on every network interface, over HTTPS with a self-signed certificate: phones only open the microphone on secure pages. The api stays on localhost; the phone reaches it through Vite. Vite prints the address under `Network`.
- `just dev` = `just models` (pron + model services in Docker, waits until healthy) + `dev-api` + `dev-ui` in parallel.
- `just desktop` starts its own Vite, so do not run it together with `just dev` or `just dev-ui`: both want port 1420.

Adding dependencies, code conventions, testing strategy and typing rules: [docs/development.md](docs/development.md).

## Desktop app and installers

**Download:** every release puts the apps on the [**Releases**](https://github.com/GeneralErdon/engish-teacher-erdon/releases/latest) page, no sign-in needed. These links always get the newest one:

| Platform | Files |
|---|---|
| Windows | [Installer (.exe)](https://github.com/GeneralErdon/engish-teacher-erdon/releases/latest/download/voice-tutor-windows-x64-setup.exe) · [.msi](https://github.com/GeneralErdon/engish-teacher-erdon/releases/latest/download/voice-tutor-windows-x64.msi) |
| Linux | [.AppImage](https://github.com/GeneralErdon/engish-teacher-erdon/releases/latest/download/voice-tutor-linux-x86_64.AppImage) · [.deb](https://github.com/GeneralErdon/engish-teacher-erdon/releases/latest/download/voice-tutor-linux-amd64.deb) · [.rpm](https://github.com/GeneralErdon/engish-teacher-erdon/releases/latest/download/voice-tutor-linux-x86_64.rpm) |
| Android (arm64) | [.apk](https://github.com/GeneralErdon/engish-teacher-erdon/releases/latest/download/voice-tutor-android-arm64.apk) |

The installers are not code-signed yet, so Windows SmartScreen asks for confirmation. To try a branch between releases, build it on GitHub's machines: `gh workflow run apps.yml --ref <branch>` (or **Run workflow** on the [Apps workflow](https://github.com/GeneralErdon/engish-teacher-erdon/actions/workflows/apps.yml)), then download the apps from the run's **Artifacts** (signed in to GitHub, kept 30 days).

Or build them on your machine:

```bash
just bundle
```

Output goes to `apps/desktop/src-tauri/target/release/bundle/`: `.deb`, `.rpm` and `.AppImage` on Linux; `.msi` and `.exe` (NSIS) on Windows. The app talks to the backend at `http://localhost:8080` by default, so start it with Docker or `just dev-api` first. To use a backend on another computer of your network, set its address in **Settings → Backend** (the app checks it before switching) and run the api there with `just dev-api 0.0.0.0`: it then listens on the network, which has no login, so only do it on networks you trust.

**On an Android phone:**

1. On the computer: `just voice` once, then `just dev-api 0.0.0.0`, so the api listens on your network (no login: trusted networks only).
2. On the phone: download the [`.apk`](https://github.com/GeneralErdon/engish-teacher-erdon/releases/latest/download/voice-tutor-android-arm64.apk) and open it. Android asks to allow installing apps from that source, the first time.
3. In the app: **Settings → Backend**, enter the computer's address (`192.168.x.x:8080`) and **Check and use**. The first call asks for the microphone.

Every APK is signed with the same key, so a new release installs over the previous one and keeps your settings.

Today the apps are **clients**: the installer contains the window and the UI, not the models. An all-in-one installer is planned for Phase 4: it starts the backend by itself and downloads the models on first run, with no Docker ([why and how](docs/architecture.md#distribution)).

## Configuration

All settings live in `.env`, starting from [`.env.example`](.env.example). They are validated at startup, so a service refuses to boot with a clear message if something is wrong.

| Variable | Default | Description |
|---|---|---|
| `VT_PROFILE` | `cpu` | Hardware profile (see below). |
| `VT_LLM_PROVIDER` | `openai_compatible` | `ollama`, `ollama_cloud`, `openai`, `anthropic`, `gemini`, `openai_compatible` or `anthropic_compatible`. Easier: pick it in the app under **Settings → Language model**, which wins over these variables ([details](docs/configuration.md#chat-model-providers)). |
| `VT_LLM_BASE_URL` | `http://llm:8080/v1` | The provider's base URL. |
| `VT_LLM_MODEL` | `gemma-3-4b-it-q4` | Model name as the endpoint expects it (`gemma-3-12b-it-q4` on a 12–16 GB GPU). |
| `VT_LLM_API_KEY` | *(empty)* | For providers that need one. Keys saved in the app stay in the backend, [encrypted](docs/configuration.md#encryption) (SQLCipher + AES-256-GCM, master key in the OS keyring). |
| `VT_LLM_HF_REPO` | `ggml-org/gemma-3-4b-it-GGUF` | GGUF that llama.cpp downloads (`cpu` / `amd` profiles). |
| `VT_STT_BASE_URL` | `http://stt:8000/v1` | Speech-to-text endpoint. |
| `VT_STT_MODEL` | `Systran/faster-distil-whisper-small.en` | Speaches model id, downloaded once ([voice setup](docs/configuration.md#voice-setup)). |
| `VT_TTS_BASE_URL` | `http://tts:8000/v1` | Text-to-speech endpoint (the same Speaches). |
| `VT_TTS_MODEL` | `speaches-ai/Kokoro-82M-v1.0-ONNX` | The tutor's voice, downloaded once ([voice setup](docs/configuration.md#voice-setup)). |
| `VT_TTS_VOICE` | `af_heart` | Tutor voice (American or British English). |
| `VT_PRON_BASE_URL` | `http://pron:8001` | Pronunciation scoring service. |
| `VT_NOTES_DIR` | `/data/notes` | Where session notes are written (mount it into your Obsidian vault if you like). |

The full reference, including the `pron` service and Docker-only variables, is in [docs/configuration.md](docs/configuration.md).

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

## Commands

Run `just` to list everything. The main recipes:

| Recipe | Does |
|---|---|
| `just setup` | Install every dependency (uv, pnpm) and the git hooks |
| `just fmt` | Format Python, TypeScript and Rust |
| `just check` | ruff, mypy --strict, import-linter, ESLint, tsc, Prettier, cargo fmt, clippy |
| `just test` | pytest, Vitest, cargo test; each fails under **97 % coverage** |
| `just dev` | Models in Docker + api and UI locally |
| `just dev-api` / `just dev-ui` | One half of `just dev` |
| `just desktop` | Tauri dev window |
| `just bundle` | Desktop installers for this OS |
| `just up [profile]` / `just watch [profile]` / `just down` | Full stack in Docker / with Compose Watch / stop it |
| `just eval` | Evaluations and README results table *(Phase 2)* |

CI runs the same `check` and `test` recipes on every pull request and every push to `master`/`develop`, compiles the desktop shell on Ubuntu **and Windows**, builds both Docker images, and scans dependencies, secrets and code (Trivy, CodeQL, dependency review). Everything that runs, what blocks a merge, and how it maps to the git hooks: [.github/README.md](.github/README.md).

## Project layout

```
.
├── apps/desktop/         # React + TypeScript UI, wrapped by Tauri 2 (src-tauri/)
├── packages/contracts/   # vt_contracts: Pydantic models shared by services and UI
├── services/api/         # vt_api: FastAPI realtime session, teacher, notes, progress
├── services/pron/        # vt_pron: pronunciation scoring
├── docs/                 # architecture, development, configuration, hardware, evaluation, roadmap
├── compose.yaml          # every service; hardware selected with --profile
├── justfile              # task runner
├── pyproject.toml        # uv workspace + ruff / mypy / pytest / import-linter config
└── package.json          # pnpm workspace root
```

The full tree, with what each module will contain, is in [docs/architecture.md](docs/architecture.md#repository-layout).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Port 1420 is already in use` when running `just desktop` | `just dev`, `just dev-ui` or `just dev-lan` is already running Vite. Stop it; `just desktop` starts its own. |
| The phone cannot open `https://<IP>:1420` | Same Wi-Fi (not a guest network that isolates devices)? On Fedora Workstation the firewall allows ports above 1024; elsewhere, open TCP 1420. Then accept the certificate warning once. |
| No sound from the tutor on an iPhone | The silent switch mutes web audio: turn it off. |
| The app says **API unreachable** | Start the backend: `just dev-api` (local) or `just up` (Docker). Check `curl http://localhost:8080/healthz`. |
| Rust build fails with `webkit2gtk-4.1` / `javascriptcoregtk` not found | The Tauri system libraries are missing: see [Install the toolchain](#install-the-toolchain). |
| `pnpm.ps1 cannot be loaded because running scripts is disabled` (Windows, outside `just`) | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. The `justfile` already bypasses it for its own recipes. |
| `api` cannot write to `./data` | The container runs as uid 1000. If your user has another uid: `docker compose build --build-arg APP_UID=$(id -u) api`. |
| `docker compose up --wait` takes a long time on first start | It is downloading models. Watch `docker compose logs -f llm-cpu` (or your profile's service). |
| The chat model download stops progressing (`download failed: Failed to read connection`) | `docker compose restart llm-cpu` resumes it; what was already downloaded stays in the `voice-tutor_llm-models` volume. |
| `uv: command not found` / `just: command not found` after installing | Open a new terminal, or add `~/.local/bin` (and `~/.cargo/bin` for Rust) to your `PATH`. |

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) (setup, branches, commits, tests) and [SECURITY.md](SECURITY.md) for reporting vulnerabilities. In short: git flow: `master` holds releases, `develop` is the integration branch, and every change gets its own `feat/<name>` or `fix/<name>` branch from `develop`, merged back by pull request with CI green ([details](docs/development.md#branches-and-commits-git-flow)). Conventional Commits (`feat:`, `fix:`, `docs:`…), small PRs with tests, and `just check test` green before pushing; the pre-commit hooks installed by `just setup` catch most issues on commit. Architecture changes get a short ADR in [docs/architecture.md](docs/architecture.md#architecture-decisions-summary).

## Privacy

- Audio is processed in memory and discarded after the turn unless you enable `VT_KEEP_AUDIO=true` for debugging.
- Notes and progress are stored locally in `./data`.
- No analytics, no external calls except to the model endpoints you configure.

## Credits

Built on [FastAPI](https://fastapi.tiangolo.com/), [Silero VAD](https://github.com/snakers4/silero-vad), [Speaches](https://github.com/speaches-ai/speaches), [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), [llama.cpp](https://github.com/ggml-org/llama.cpp), [Ollama](https://ollama.com/), [Tauri](https://tauri.app/) and wav2vec2 phoneme models. Check each model's license before redistributing it (see [docs/evaluation.md#licenses](docs/evaluation.md#licenses)).

## License

Not decided yet (MIT is the planned default). See [docs/roadmap.md](docs/roadmap.md).
