import io
import wave

from vt_api.domain.audio import duration_s, to_wav

ONE_SECOND = bytes(32_000)  # 16 kHz x 2 bytes


def test_duration() -> None:
    assert duration_s(len(ONE_SECOND)) == 1.0
    assert duration_s(48_000, sample_rate=24_000) == 1.0


def test_wav_wraps_the_pcm() -> None:
    with wave.open(io.BytesIO(to_wav(ONE_SECOND))) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16_000)
        assert wav.readframes(wav.getnframes()) == ONE_SECOND
