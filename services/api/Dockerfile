# syntax=docker/dockerfile:1
#
# voice-tutor api (+ the browser build of the UI).
# Build context is the repository root: the uv workspace needs the root pyproject.toml and uv.lock.
#   docker build -f services/api/Dockerfile -t voice-tutor-api .

ARG PYTHON_VERSION=3.14
ARG NODE_VERSION=24
ARG UV_VERSION=0.13.4

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------------------------------------------------------------- ui: React build served in browser mode
FROM node:${NODE_VERSION}-trixie-slim AS ui
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
# corepack installs the exact pnpm pinned in package.json#packageManager.
RUN corepack enable
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/desktop/package.json apps/desktop/
RUN --mount=type=cache,id=pnpm-store,target=/pnpm-store \
    pnpm install --frozen-lockfile --store-dir /pnpm-store --filter @voice-tutor/desktop
COPY apps/desktop apps/desktop
RUN pnpm --filter @voice-tutor/desktop build

# ---------------------------------------------------------------- build: virtualenv with uv
FROM python:${PYTHON_VERSION}-slim-trixie AS build
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# 1. Third-party dependencies only: this layer is reused until uv.lock changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=packages/contracts/pyproject.toml,target=packages/contracts/pyproject.toml \
    --mount=type=bind,source=services/api/pyproject.toml,target=services/api/pyproject.toml \
    --mount=type=bind,source=services/pron/pyproject.toml,target=services/pron/pyproject.toml \
    uv sync --frozen --no-dev --no-install-workspace --package vt-api

# 2. Our code (vt-api + vt-contracts), installed as regular (non-editable) packages.
COPY pyproject.toml uv.lock ./
COPY packages/contracts packages/contracts
COPY services/api services/api
COPY services/pron/pyproject.toml services/pron/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package vt-api

# ---------------------------------------------------------------- runtime: only the venv and the UI
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime
# Matches the usual first desktop user on Linux, so files in the ./data bind mount stay yours.
ARG APP_UID=1000
RUN groupadd --gid ${APP_UID} app \
    && useradd --uid ${APP_UID} --gid app --no-create-home --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir /data && chown app:app /data

COPY --from=build /app/.venv /app/.venv
COPY --from=ui /src/apps/desktop/dist /app/ui

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    VT_HOST=0.0.0.0 \
    VT_PORT=8080 \
    VT_UI_DIR=/app/ui
WORKDIR /app
USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['VT_PORT'] + '/healthz', timeout=3)"]

# uvicorn, configured from VT_HOST / VT_PORT / VT_LOG_LEVEL (see vt_api/__main__.py).
CMD ["vt-api"]
