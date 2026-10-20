# Development guide

## Toolchain

Versions were verified on **2026-10-20** (Phase -1). Bump them on purpose, never by accident: every one is pinned in a file that tools and CI read.

| Concern | Python (`packages/*`, `services/*`) | Web + desktop (`apps/desktop`) |
|---|---|---|
| Runtime | **Python 3.14** (`.python-version`). Rule: the latest stable Python **for which torch, onnxruntime and ctranslate2 publish wheels**. Python 3.15.0 is out (2026-10-09), but torch 2.14, onnxruntime 1.31 and ctranslate2 4.8 ship wheels only up to cp314, so we stay on 3.14 until they catch up. | **Node 24 LTS** (`.nvmrc`); Node 26 becomes LTS on 2026-10-28. **Rust 1.99.1** (`rust-toolchain.toml`) |
| Packages | [**uv**](https://docs.astral.sh/uv/) workspace: one `uv.lock`, `uv add`, `uv run`. No pip, Poetry or `requirements.txt` | **pnpm 12** workspace (`pnpm-workspace.yaml`, version pinned in `package.json#packageManager`): one `pnpm-lock.yaml` |
| Framework | FastAPI, Pydantic v2, pydantic-settings, uvicorn | React 19, Vite 8, Tauri 2 |
| Lint + format | **ruff** (`ruff check`, `ruff format`) | ESLint 10 (flat config, `typescript-eslint` strict type-checked) + Prettier; `cargo fmt` + `cargo clippy -D warnings` (pedantic) |
| Types | **mypy `--strict`** + pydantic plugin | TypeScript **6.0** strict (`tsc -b`); see the note below |
| Architecture | import-linter contracts (layering, service independence) | Tauri capabilities (least privilege) |
| Tests | **pytest 9**, pytest-asyncio, pytest-cov, hypothesis (property tests), httpx2 (ASGI client) | Vitest + Testing Library (jsdom); `cargo test` |
| Tensor typing | `jaxtyping` + `beartype`, added with torch in Phase 2 | — |
| Tasks | [**just**](https://just.systems) (`justfile`): one entry point on Linux, macOS and **Windows** (make does not run natively there) | |
| Hooks | pre-commit (ruff, mypy, import-linter, uv-lock, eslint, prettier, cargo fmt, large-file and private-key guards) | |

Notes on choices that are not the newest thing available:

- **TypeScript 6.0, not 7.** TypeScript 7 (the Go-native compiler) is out, but `typescript-eslint` supports `typescript <6.1`, and type-aware linting matters more here than compile speed. Move to 7 when `typescript-eslint` does.
- **ESLint, not oxlint.** `create-vite` now defaults to oxlint (faster, fewer type-aware rules). Kept ESLint + `typescript-eslint` strict type-checked as the docs specified; revisit if lint time becomes a problem.
- **mypy, not ty.** Astral's `ty` is still beta (0.0.x, `Development Status :: 4 - Beta`). It can be tried with `uvx ty check`, but mypy `--strict` stays the gate until ty is stable.
- **httpx2.** Starlette 1.x prefers `httpx2` (the maintained fork) for its test client; `respx` still targets `httpx`, so the HTTP-mocking library for adapter contract tests is chosen in Phase 1 together with the adapters' HTTP client.

### First-time setup

```bash
# uv (Python + packaging) and just (task runner), both user-level, no sudo
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install rust-just

# Rust, for the desktop app (rust-toolchain.toml selects the exact version)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Node 24 (e.g. `nvm install 24`); pnpm switches itself to the pinned version
npm install -g pnpm

# Tauri 2 system dependencies
#   Fedora:  sudo dnf install webkit2gtk4.1-devel openssl-devel curl wget file \
#              libappindicator-gtk3-devel librsvg2-devel libxdo-devel
#            sudo dnf group install c-development
#   Debian/Ubuntu: see .github/workflows/ci.yml (apt list)
#   Windows: WebView2 runtime (preinstalled on 10/11) + "Desktop development with C++" build tools

just setup
```

Windows: `winget install astral-sh.uv Casey.Just Rustlang.Rustup OpenJS.NodeJS.LTS pnpm.pnpm`, then `just setup`. The `justfile` runs recipes with PowerShell there (`-ExecutionPolicy Bypass`, so the npm/pnpm `.ps1` shims work).

## just recipes

Run `just` to list them. The Docker profile comes from `VT_PROFILE` in `.env` (default `cpu`).

| Recipe | Does |
|---|---|
| `just setup` | `uv sync --all-packages`, `pnpm install`, `pre-commit install` |
| `just fmt` | ruff (fix + format), prettier, cargo fmt |
| `just check` | ruff, mypy --strict, import-linter, eslint, tsc, prettier --check, cargo fmt --check, clippy (`check-py`, `check-ui`, `check-rust` run each part) |
| `just test` | pytest with coverage, vitest, cargo test (`test-py`, `test-ui`, `test-rust`) |
| `just types` | Regenerate `apps/desktop/src/generated` from `vt_contracts` *(Phase 1)* |
| `just dev` | `pron` and the profile's model services in Docker; `api` (uvicorn --reload) and the UI (Vite, http://localhost:1420) locally |
| `just dev-api` / `just dev-ui` | One half of `just dev` |
| `just desktop` | `tauri dev` window (it starts its own Vite on :1420, so do not combine it with `just dev`; run `just models` + `just dev-api`, or `just up`, for the backend) |
| `just bundle` | `tauri build` installers for the current OS (CI builds Windows + Linux) |
| `just up [profile]` | Full stack in Docker (`just up amd`) |
| `just watch [profile]` | Full stack in Docker with Compose Watch: api/pron images are rebuilt when their code changes |
| `just down` | Stop every service |
| `just eval` | Run evaluations and refresh the README results table *(Phase 2)* |

`just dev` vs `just watch`: `dev` runs the api on your machine with instant reload and a debugger-friendly process; `watch` runs exactly the production images and rebuilds them on change (a few seconds, thanks to the uv and pnpm cache mounts).

CI (`.github/workflows/ci.yml`) runs `just check-*` and `just test-*` per stack, Rust on Ubuntu **and Windows**, and builds both Docker images. From Phase 1 it also fails if `just types` or the README results block would change (generated files must be committed up to date).

### Desktop app notes

- The window's Content Security Policy (`src-tauri/tauri.conf.json`) only allows `connect-src` to `localhost:8080` / `127.0.0.1:8080`, so a desktop build talks to the local backend only. Pointing it at a home-lab server (`VITE_BACKEND_URL`, or the backend-URL setting planned for Phase 1) also needs that host in `connect-src`.
- `capabilities/main.json` grants no Tauri permissions: the UI talks to the api over HTTP/WebSocket. Add the one permission a feature needs, never a whole plugin's defaults.

### Adding dependencies

```bash
uv add --package vt-api httpx2                 # runtime dependency of one service
uv add --dev pytest-xdist                      # dev tool for the whole workspace ([dependency-groups])
pnpm --filter @voice-tutor/desktop add zod     # UI dependency
cargo add --manifest-path apps/desktop/src-tauri/Cargo.toml cpal
```

Commit `uv.lock`, `pnpm-lock.yaml` and `Cargo.lock` together with the change.

## Code conventions

- **Layering rule**: `domain` imports nothing from `adapters`, `http` or `realtime`. `ports` are `typing.Protocol`s. Wiring happens only in `container.py`. Enforced by the `import-linter` contracts in the root `pyproject.toml` (`just check`).
- **No `Any` at boundaries**: external payloads are parsed into Pydantic models immediately; internal code receives typed objects.
- **Value objects are immutable**: `@dataclass(frozen=True, slots=True)` or Pydantic models with `frozen=True`.
- **Async everywhere in `api`**: no blocking calls in the event loop. CPU-bound work (VAD on large buffers, resampling) goes through `anyio.to_thread` or the `pron` service.
- **Cancellation-safe**: any coroutine in the turn pipeline must clean up on `CancelledError` (close streams, release buffers) and re-raise.
- **Prompts are code**: templates live in `teacher/prompts/*.md`, are versioned, and have snapshot tests.
- **Structured LLM output**: corrections are requested as JSON and validated with Pydantic; invalid output triggers one repair attempt and then degrades gracefully (no correction shown, error logged).
- **Logging**: `structlog`, JSON in containers, pretty in dev; include `session_id` and `turn_id` on every log line.
- **Config**: only through `Settings` (pydantic-settings, `VT_` prefix). No `os.getenv` elsewhere.

## Typing ML code

```python
from jaxtyping import Float
from torch import Tensor


def phoneme_posteriors(audio: Float[Tensor, "samples"]) -> Float[Tensor, "frames vocab"]: ...
```

- Audio in Python is `numpy.typing.NDArray[np.float32]` (mono, [-1, 1]) at the boundaries, `torch.Tensor` only inside `vt_pron.recognizer`.
- Sample rate travels with the data (`AudioClip(samples, sample_rate)` value object); never assume it.

## Testing strategy

| Layer | What | How |
|---|---|---|
| Unit | Scoring, alignment, corrections parsing, progress aggregation, audio framing | Pure functions; hypothesis for alignment invariants |
| Contract | Each adapter against a recorded/fake server | HTTP mocks (respx or the httpx2 equivalent, decided in Phase 1) and fixture responses; one test per port method |
| Realtime | Full WS session with fake STT/LLM/TTS adapters | Starlette `TestClient` WebSocket; asserts event order, barge-in cancellation, error paths |
| Golden audio | `pron` on short WAV fixtures with known verdicts | Tolerance-based assertions; runs on CPU in CI |
| Eval (not CI) | L2-ARCTIC + latency | `just eval`; results committed to `eval/results/` |
| UI | Audio worklet framing, WS client, Markdown rendering is sanitised | Vitest + Testing Library |
| Desktop | Permission handler logic, native audio framing | `cargo test`; manual smoke test of mic on Windows and Linux before each release |

Coverage target: 85 % for `domain`, `teacher`, `vt_pron.scoring` and `vt_pron.alignment`. Do not chase coverage in adapters; contract tests matter more.

## Branches and commits (git flow)

| Branch | Purpose | Branches from | Merges into |
|---|---|---|---|
| `master` | Released code only; every merge is tagged `vX.Y.Z` | — | — |
| `develop` | Integration branch: the next release | `master` | — |
| `feat/<short-name>` | One feature | `develop` | `develop` (PR) |
| `fix/<short-name>` | One bug fix | `develop` | `develop` (PR) |
| `release/X.Y.Z` | Freeze, version bump, changelog | `develop` | `master` + back into `develop` |
| `hotfix/<short-name>` | Urgent fix on released code | `master` | `master` + `develop` |

- Never commit directly to `master` or `develop`: open a PR, and merge it only with CI green.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `ci:`).
- Small PRs, each with tests; `master` is always releasable.
- Architecture changes get a short ADR appended to the table in [architecture.md](architecture.md#architecture-decisions-summary).
