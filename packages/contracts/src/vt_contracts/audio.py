"""Audio formats on the wire (see docs/architecture.md, "Realtime protocol")."""

from typing import Final

SAMPLE_WIDTH_BYTES: Final = 2
"""PCM16 little-endian, mono, in both directions."""

INPUT_SAMPLE_RATE_HZ: Final = 16_000
"""Client to server (microphone)."""

INPUT_FRAME_MS: Final = 20
INPUT_FRAME_SAMPLES: Final = INPUT_SAMPLE_RATE_HZ * INPUT_FRAME_MS // 1000
INPUT_FRAME_BYTES: Final = INPUT_FRAME_SAMPLES * SAMPLE_WIDTH_BYTES

OUTPUT_SAMPLE_RATE_HZ: Final = 24_000
"""Server to client (TTS, Kokoro's native rate), chunked as produced."""
