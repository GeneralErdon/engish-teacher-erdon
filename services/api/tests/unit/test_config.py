from pathlib import Path

import pytest
from pydantic import ValidationError

from vt_api.config import Settings
from vt_api.domain.speech import DEFAULT_GPU_MODEL


def test_defaults_match_docs() -> None:
    settings = Settings(_env_file=None)

    assert settings.port == 8080
    assert str(settings.llm_base_url) == "http://llm:8080/v1"
    assert settings.learner_level == "B1"
    assert settings.llm_api_key.get_secret_value() == ""
    assert settings.llm_provider == "openai_compatible"
    assert settings.database_url == "sqlite:////data/voice-tutor.db"
    assert settings.secret_key is None
    assert str(settings.secret_key_file) == "/data/secret.key"
    assert settings.keyring is True
    assert settings.learner_explanations == "native"


def test_reads_vt_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_LLM_MODEL", "qwen3-14b")
    monkeypatch.setenv("VT_KEEP_AUDIO", "true")
    monkeypatch.setenv("VT_LLM_PROVIDER", "ollama_cloud")

    settings = Settings(_env_file=None)

    assert settings.llm_model == "qwen3-14b"
    assert settings.llm_provider == "ollama_cloud"
    assert settings.keep_audio is True


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("VT_LEARNER_LEVEL", "D1"),
        ("VT_PROFILE", "tpu"),
        ("VT_TTS_SPEED", "3"),
        ("VT_LLM_BASE_URL", "not a url"),
        ("VT_LLM_PROVIDER", "mistral"),
        ("VT_UI_DIR", "/does/not/exist"),
        ("VT_DATABASE_URL", "postgresql://db/voice"),
        ("VT_STT_BACKEND", "whisper"),
        ("VT_STT_GPU_MODEL", "ggml-small.bin"),  # not a file of a repository
        ("VT_STT_GPU_MODELS_ROOT", "models"),  # a path in the server's container: absolute
    ],
)
def test_invalid_values_fail_at_startup(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_empty_values_mean_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_UI_DIR", "")
    monkeypatch.setenv("VT_PORT", "")

    settings = Settings(_env_file=None)

    assert settings.ui_dir is None
    assert settings.port == 8080


@pytest.mark.parametrize(
    ("name", "value"), [("VT_MAX_TURN_S", "20"), ("VT_MAX_TURN_S", "301"), ("VT_TTS_SPEED", "1.5")]
)
def test_speech_limits_are_enforced(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_speech_models_dir_and_turn_length(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings(_env_file=None).speech_models_dir is None
    assert Settings(_env_file=None).max_turn_s == 120

    monkeypatch.setenv("VT_SPEECH_MODELS_DIR", "data/models")

    assert Settings(_env_file=None).speech_models_dir == Path("data/models")


def test_the_gpu_engine_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None)

    assert settings.stt_backend == "openai"
    assert str(settings.stt_gpu_base_url) == "http://stt-gpu:8080/v1"
    assert settings.stt_gpu_models_root == "/models"
    assert settings.stt_gpu_model == DEFAULT_GPU_MODEL

    monkeypatch.setenv("VT_STT_BACKEND", "whispercpp")
    monkeypatch.setenv("VT_STT_GPU_MODEL", "ggerganov/whisper.cpp/ggml-base.en.bin")

    settings = Settings(_env_file=None)
    assert (settings.stt_backend, settings.stt_gpu_model) == (
        "whispercpp",
        "ggerganov/whisper.cpp/ggml-base.en.bin",
    )
