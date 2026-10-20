# syntax=docker/dockerfile:1
#
# voice-tutor pronunciation scoring service.
# Build context is the repository root: the uv workspace needs the root pyproject.toml and uv.lock.
#   docker build -f services/pron/Dockerfile -t voice-tutor-pron .
#
# Phase 2 adds torch. Use the CPU-only wheels (an extra uv index for the pytorch-cpu
# channel) or this image grows by several GB of CUDA libraries it never uses.

ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.13.4

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

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
    uv sync --frozen --no-dev --no-install-workspace --package vt-pron

# 2. Our code (vt-pron + vt-contracts), installed as regular (non-editable) packages.
COPY pyproject.toml uv.lock ./
COPY packages/contracts packages/contracts
COPY services/pron services/pron
COPY services/api/pyproject.toml services/api/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package vt-pron

# ---------------------------------------------------------------- runtime: only the venv
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime
ARG APP_UID=1000
RUN groupadd --gid ${APP_UID} app \
    && useradd --uid ${APP_UID} --gid app --no-create-home --home-dir /app --shell /usr/sbin/nologin app

COPY --from=build /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    VT_PRON_HOST=0.0.0.0 \
    VT_PRON_PORT=8001
WORKDIR /app
USER app
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['VT_PRON_PORT'] + '/healthz', timeout=3)"]

# uvicorn, configured from VT_PRON_HOST / VT_PRON_PORT / VT_PRON_LOG_LEVEL.
CMD ["vt-pron"]
