# vt-contracts

Pydantic models for every message that crosses a process boundary. They are the single source of
truth: the TypeScript types in `apps/desktop/src/generated` are generated from their JSON Schema
(`just types`, Phase 1).

| Module | Contents |
|---|---|
| `audio.py` | Audio format constants (sample rates, frame size) |
| `health.py` | `/healthz` response shared by `api` and `pron` |
| `ws.py` | *(Phase 1)* discriminated unions of client/server WebSocket events |
| `pron.py` | *(Phase 2)* `ScoreRequest` / `ScoreResponse` |
