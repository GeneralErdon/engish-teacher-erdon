# voice-tutor task runner: `just` lists the recipes, `just <recipe>` runs one.
# Same commands on Linux, macOS and Windows. Install: `uv tool install rust-just`.

# Bypass: npm/pnpm install .ps1 shims that the default Restricted policy refuses to run.
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
# .env (if present) feeds the variables below, e.g. VT_PROFILE.
set dotenv-load

# Hardware profile for Docker Compose: cpu | nvidia | amd | external (docs/hardware.md)
PROFILE := env("VT_PROFILE", "cpu")

# Where `just dev` finds the chat model from the host. `external` reuses your own server URL.
LLM_DEV_URL := if PROFILE == "external" { replace(env("VT_LLM_BASE_URL", "http://localhost:11434/v1"), "host.docker.internal", "localhost") } else { "http://localhost:8081/v1" }

desktop := "@voice-tutor/desktop"
tauri_manifest := "apps/desktop/src-tauri/Cargo.toml"

[private]
default:
    @just --list --unsorted

# Install every dependency and the git hooks
[group('setup')]
setup:
    uv sync --all-packages
    pnpm install
    uv run pre-commit install

# Format Python, TypeScript and Rust
[group('quality')]
fmt:
    uv run ruff check --fix .
    uv run ruff format .
    pnpm --filter {{ desktop }} format
    cargo fmt --manifest-path {{ tauri_manifest }}

# Lint and type-check everything (what CI runs)
[group('quality')]
check: check-py check-ui check-rust

# ruff, mypy --strict (per workspace member), import-linter layering contracts
[group('quality')]
check-py:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy packages/contracts/src packages/contracts/tests
    uv run mypy services/api/src services/api/tests
    uv run mypy services/pron/src services/pron/tests
    uv run lint-imports

# ESLint (type-aware), tsc --noEmit, Prettier
[group('quality')]
check-ui:
    pnpm --filter {{ desktop }} lint
    pnpm --filter {{ desktop }} typecheck
    pnpm --filter {{ desktop }} format:check

# cargo fmt + clippy with warnings as errors
[group('quality')]
check-rust:
    cargo fmt --manifest-path {{ tauri_manifest }} --check
    cargo clippy --manifest-path {{ tauri_manifest }} --all-targets --locked -- -D warnings

# Run every test suite
[group('quality')]
test: test-py test-ui test-rust

# pytest (unit + integration) with coverage
[group('quality')]
test-py:
    uv run pytest --cov --cov-report=term

# Vitest
[group('quality')]
test-ui:
    pnpm --filter {{ desktop }} test

# cargo test (permission policy, audio framing)
[group('quality')]
test-rust:
    cargo test --manifest-path {{ tauri_manifest }} --locked

# Regenerate apps/desktop/src/generated from vt_contracts
[group('quality')]
types:
    @echo "not implemented yet: arrives with vt_contracts.ws in Phase 1 (docs/roadmap.md)"

# Model services in Docker; api (auto-reload) and UI (Vite) locally, in the browser
[group('dev')]
dev: models _serve

[parallel]
[private]
_serve: dev-api dev-ui

# Start pron and the PROFILE's model services in Docker and wait until they are healthy
[group('dev')]
models:
    docker compose --profile {{ PROFILE }} up -d --build --wait --scale api=0

# api on :8080 with auto-reload, using the model services published on localhost
[env("VT_DB_PATH", "data/progress.db")]
[env("VT_LLM_BASE_URL", LLM_DEV_URL)]
[env("VT_NOTES_DIR", "data/notes")]
[env("VT_PRON_BASE_URL", "http://localhost:8001")]
[env("VT_STT_BASE_URL", "http://localhost:8000/v1")]
[env("VT_TTS_BASE_URL", "http://localhost:8880/v1")]
[group('dev')]
dev-api:
    uv run uvicorn --factory vt_api.main:create_app --reload --reload-dir services/api/src --reload-dir packages/contracts/src --port 8080

# UI on http://localhost:1420 (Vite, hot reload)
[group('dev')]
dev-ui:
    pnpm --filter {{ desktop }} dev

# Tauri dev window (starts its own Vite). Backend: `just models` + `just dev-api`, or `just up`
[group('dev')]
desktop:
    pnpm --filter {{ desktop }} tauri dev

# Installers for the current OS (CI builds Windows and Linux)
[group('release')]
bundle:
    pnpm --filter {{ desktop }} tauri build

# Full stack in Docker: `just up` or `just up amd`
[group('docker')]
up profile=PROFILE:
    docker compose --profile {{ profile }} up -d --build --wait

# Full stack in Docker, rebuilding api/pron when their code changes (Compose Watch)
[group('docker')]
watch profile=PROFILE:
    docker compose --profile {{ profile }} up --build --watch

# Stop every service of every profile
[group('docker')]
down:
    docker compose --profile "*" down

# Run the evaluations and refresh the README results table
[group('eval')]
eval: eval-pron eval-latency

# Mispronunciation detection on L2-ARCTIC: `just eval-pron /path/to/l2-arctic`
[group('eval')]
eval-pron DATASET_DIR="":
    @echo "not implemented yet: Phase 2 (docs/evaluation.md)"

# Voice-to-voice latency on the reference machine
[group('eval')]
eval-latency:
    @echo "not implemented yet: Phase 2 (docs/evaluation.md)"
