"""Audio from the learner's microphone: PCM16 little-endian, mono (`vt_contracts.audio`)."""

import io
import wave

from vt_contracts.audio import INPUT_SAMPLE_RATE_HZ, SAMPLE_WIDTH_BYTES


def duration_s(size_bytes: int, sample_rate: int = INPUT_SAMPLE_RATE_HZ) -> float:
    """Seconds of audio in `size_bytes` of PCM16 mono."""
    return size_bytes / (SAMPLE_WIDTH_BYTES * sample_rate)


def to_wav(pcm: bytes | bytearray, sample_rate: int = INPUT_SAMPLE_RATE_HZ) -> bytes:
    """Wrap raw PCM in a WAV container, the format every speech-to-text server accepts."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(SAMPLE_WIDTH_BYTES)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(pcm))
    return buffer.getvalue()
