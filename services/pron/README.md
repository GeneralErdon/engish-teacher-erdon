# vt-pron

Pronunciation scoring service: `POST /v1/score` (Phase 2) and `GET /healthz`.

```bash
uv run --package vt-pron vt-pron   # honours VT_PRON_HOST / VT_PRON_PORT
```

Pipeline (G2P, recognizer, alignment, scoring): [docs/architecture.md](../../docs/architecture.md#pronunciation-scoring-pron).
