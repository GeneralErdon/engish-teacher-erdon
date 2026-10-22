import pytest
from pydantic import ValidationError

from vt_api.config import Settings


def test_defaults_match_docs() -> None:
    settings = Settings(_env_file=None)

    assert settings.port == 8080
    assert str(settings.llm_base_url) == "http://llm:8080/v1"
    assert settings.learner_level == "B1"
    assert settings.llm_api_key.get_secret_value() == ""
    assert settings.llm_provider == "openai_compatible"
    assert str(settings.settings_path) == "/data/settings.json"
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
        ("VT_VAD_THRESHOLD", "1.5"),
        ("VT_LLM_BASE_URL", "not a url"),
        ("VT_LLM_PROVIDER", "mistral"),
        ("VT_UI_DIR", "/does/not/exist"),
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
