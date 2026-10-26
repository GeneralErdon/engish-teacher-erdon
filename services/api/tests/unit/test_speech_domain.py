import pytest

from vt_api.domain.speech import (
    CATALOG,
    DEFAULT_GPU_MODEL,
    SpeechSettingsError,
    catalog,
    entry,
    entry_for,
    single_file_repos,
    split_model_id,
    transcription_timeout_s,
)

DEFAULT_STT = "Systran/faster-distil-whisper-small.en"
DEFAULT_TTS = "speaches-ai/Kokoro-82M-v1.0-ONNX"
SMALL_Q8 = "ggerganov/whisper.cpp/ggml-small.en-q8_0.bin"


def test_catalog_lists_the_curated_models_in_order() -> None:
    assert [e.key for e in catalog("recognition", DEFAULT_STT)] == [
        "whisper-tiny-en",
        "whisper-base-en",
        "distil-whisper-small-en",
        "whisper-small-en",
        "distil-whisper-medium-en",
        "whisper-medium-en",
        "distil-whisper-large-v3",
        "whisper-large-v3-turbo",
    ]
    voices = catalog("voice", DEFAULT_TTS)
    assert [e.key for e in voices] == [
        "kokoro",
        "kokoro-int8",
        "piper-lessac",
        "piper-ryan",
        "piper-alba",
        "piper-alan",
    ]
    assert [e.model_id for e in voices] == [
        "speaches-ai/Kokoro-82M-v1.0-ONNX",
        "speaches-ai/Kokoro-82M-v1.0-ONNX-int8",
        "speaches-ai/piper-en_US-lessac-medium",
        "speaches-ai/piper-en_US-ryan-medium",
        "speaches-ai/piper-en_GB-alba-medium",
        "speaches-ai/piper-en_GB-alan-medium",
    ]


def test_piper_entries_ask_for_the_output_rate() -> None:
    piper = [e for e in CATALOG if e.key.startswith("piper-")]

    assert len(piper) == 4
    assert all(e.sample_rate_hz == 24000 for e in piper)
    assert all(e.sample_rate_hz is None for e in CATALOG if e.key.startswith("kokoro"))


def test_an_unknown_default_is_added_from_configuration() -> None:
    models = catalog("recognition", "acme/whisper-x")

    assert models[-1].model_id == "acme/whisper-x"
    assert models[-1].key.startswith("configured-")
    assert len({e.key for e in models}) == len(models)
    assert entry(models[-1].key) is None


def test_a_listed_default_is_not_duplicated() -> None:
    assert len(catalog("recognition", DEFAULT_STT)) == 8


def test_speaches_lists_only_its_own_models() -> None:
    speaches = catalog("recognition", DEFAULT_STT) + catalog("voice", DEFAULT_TTS)

    assert {e.engine for e in speaches} == {"openai"}


def test_the_gpu_catalog_lists_whisper_cpp_files() -> None:
    gpu = catalog("recognition", SMALL_Q8, "whispercpp")

    assert [(e.key, e.model_id, e.label, e.hint, e.approx_mb, e.english_only) for e in gpu] == [
        (
            "whispercpp-base-en",
            "ggerganov/whisper.cpp/ggml-base.en.bin",
            "Whisper base (English)",
            "Fastest, least accurate",
            148,
            True,
        ),
        (
            "whispercpp-small-en-q8",
            SMALL_Q8,
            "Whisper small (English, 8-bit)",
            "Fast and accurate on a GPU",
            264,
            True,
        ),
        (
            "whispercpp-medium-en-q5",
            "ggerganov/whisper.cpp/ggml-medium.en-q5_0.bin",
            "Whisper medium (English, 5-bit)",
            "More accurate",
            539,
            True,
        ),
        (
            "whispercpp-large-v3-turbo-q5",
            "ggerganov/whisper.cpp/ggml-large-v3-turbo-q5_0.bin",
            "Whisper large v3 turbo (5-bit)",
            "The accurate choice (multilingual)",
            574,
            False,
        ),
        (
            "whispercpp-large-v3-turbo-q8",
            "ggerganov/whisper.cpp/ggml-large-v3-turbo-q8_0.bin",
            "Whisper large v3 turbo (8-bit)",
            "Most accurate; more GPU memory (multilingual)",
            874,
            False,
        ),
        (
            "whispercpp-large-v3-turbo",
            "ggerganov/whisper.cpp/ggml-large-v3-turbo.bin",
            "Whisper large v3 turbo (full)",
            "Full precision; the most GPU memory (multilingual)",
            1625,
            False,
        ),
    ]
    assert {(e.kind, e.engine) for e in gpu} == {("recognition", "whispercpp")}
    assert DEFAULT_GPU_MODEL == SMALL_Q8


def test_an_unknown_gpu_default_is_added_for_its_engine() -> None:
    models = catalog("recognition", "acme/ggml/ggml-tiny.bin", "whispercpp")

    assert (models[-1].key, models[-1].model_id, models[-1].engine) == (
        "configured-ggml-tiny-bin",
        "acme/ggml/ggml-tiny.bin",
        "whispercpp",
    )
    assert len(models) == 7


def test_single_file_repos_hold_the_gpu_models() -> None:
    assert single_file_repos(DEFAULT_GPU_MODEL) == {"ggerganov/whisper.cpp"}
    assert single_file_repos("acme/ggml/ggml-tiny.bin") == {"ggerganov/whisper.cpp", "acme/ggml"}


def test_entries_are_found_by_key_and_by_model_id() -> None:
    assert entry("piper-alan") is entry_for("speaches-ai/piper-en_GB-alan-medium")
    assert entry("nope") is None
    assert entry_for("nope/nope") is None


def test_transcription_timeout_grows_with_the_audio() -> None:
    assert transcription_timeout_s(10) == 60
    assert transcription_timeout_s(300) == 930


def test_a_settings_error_carries_status_and_message() -> None:
    error = SpeechSettingsError(409, "Another download is running.")

    assert (error.status, error.message) == (409, "Another download is running.")
    assert str(error) == "Another download is running."


def test_split_model_id() -> None:
    # `org/name` is a whole repository, `org/name/file.bin` one file of it.
    assert split_model_id("org/name") == ("org/name", None)
    assert split_model_id("org/name/file.bin") == ("org/name", "file.bin")


@pytest.mark.parametrize("model_id", ["a/b/c/d", "a//b", "a", "", "a/b/"])
def test_split_model_id_refuses_what_names_no_model(model_id: str) -> None:
    with pytest.raises(ValueError, match="Not a repo id"):
        split_model_id(model_id)
