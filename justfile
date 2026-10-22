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

# Coverage floor for every language. Never lower it to make a build pass (docs/development.md#testing).
COVERAGE_MIN := "97"

# Rust files that need a real window/webview: excluded from coverage (see src-tauri/src/shell.rs).
rust_cov_ignore := "(main|shell)\\.rs$"

[private]
default:
    @just --list --unsorted

# Install every dependency and the git hooks
[group('setup')]
setup:
    uv sync --all-packages
    pnpm install
    cargo install --locked cargo-llvm-cov
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

# Run every test suite, each with its 97% coverage floor (what CI runs)
[group('quality')]
test: test-py test-ui test-rust

# pytest (unit + integration); fails under 97% coverage. Writes coverage.xml
[group('quality')]
test-py:
    uv run pytest --cov --cov-report=term-missing:skip-covered --cov-report=xml

# Vitest; fails under 97% coverage. Writes apps/desktop/coverage/ (lcov + html)
[group('quality')]
test-ui:
    pnpm --filter {{ desktop }} test:cov

# cargo test under cargo-llvm-cov; fails under 97% coverage. Writes src-tauri/target/lcov.info
[group('quality')]
test-rust:
    cargo llvm-cov --manifest-path {{ tauri_manifest }} --locked --no-report
    cargo llvm-cov report --manifest-path {{ tauri_manifest }} --ignore-filename-regex '{{ rust_cov_ignore }}' --summary-only --fail-under-lines {{ COVERAGE_MIN }} --fail-under-functions {{ COVERAGE_MIN }} --fail-under-regions {{ COVERAGE_MIN }}
    cargo llvm-cov report --manifest-path {{ tauri_manifest }} --ignore-filename-regex '{{ rust_cov_ignore }}' --lcov --output-path apps/desktop/src-tauri/target/lcov.info

# Fast test run without coverage (used by the pre-push hook)
[group('quality')]
test-fast:
    uv run pytest -q
    pnpm --filter {{ desktop }} test
    cargo test --manifest-path {{ tauri_manifest }} --locked

# Known vulnerabilities in every lockfile, secrets and Dockerfile issues (needs Trivy installed)
[group('quality')]
security:
    uv audit --locked --preview-features audit-command
    pnpm audit --audit-level high
    trivy fs --config trivy.yaml .

# Regenerate the UI's API types: api OpenAPI schema -> apps/desktop/src/generated/api.d.ts
[group('quality')]
types:
    uv run vt-api-openapi apps/desktop/openapi.json
    pnpm --filter {{ desktop }} types

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
[env("VT_LEARNER_PROFILE_PATH", "data/learner.json")]
[env("VT_SETTINGS_PATH", "data/settings.json")]
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
