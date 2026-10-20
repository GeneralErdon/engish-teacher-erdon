from vt_contracts import audio


def test_input_frame_is_20ms_of_pcm16_at_16khz() -> None:
    assert audio.INPUT_FRAME_SAMPLES == 320
    assert audio.INPUT_FRAME_BYTES == 640


def test_output_rate_matches_kokoro() -> None:
    assert audio.OUTPUT_SAMPLE_RATE_HZ == 24_000
