# vt-api

FastAPI service: realtime voice session (`/ws/session`), teacher logic, notes and progress.
It also serves the built UI (`VT_UI_DIR`) for the browser / home-lab mode.

```bash
uv run --package vt-api vt-api                                   # honours VT_HOST / VT_PORT
uv run uvicorn --factory vt_api.main:create_app --reload --port 8080  # dev (what `just dev` runs)
```

Layout and layering rules: [docs/architecture.md](../../docs/architecture.md) and
[docs/development.md](../../docs/development.md).
