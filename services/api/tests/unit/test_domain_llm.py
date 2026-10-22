import pytest
from pydantic import SecretStr

from vt_api.domain.llm import (
    PROVIDERS,
    InvalidSettingsError,
    LlmConfig,
    ProviderConfig,
    environment_config,
    resolve_connection,
    to_view,
    with_provider,
)
from vt_contracts.llm import ProviderConnection, ProviderSettingsInput

ANTHROPIC_URL = "https://api.anthropic.com"
LONG_KEY = "sk-ant-0123456789abcd"


def _saved(*providers: ProviderConfig) -> LlmConfig:
    return LlmConfig(
        active=providers[0].kind, providers={p.kind: p for p in providers}, source="saved"
    )


def _anthropic(key: str = LONG_KEY, url: str = ANTHROPIC_URL) -> ProviderConfig:
    return ProviderConfig("anthropic", url, "claude-opus-5-5", SecretStr(key))


def test_catalogue_covers_every_kind_with_a_consistent_preset() -> None:
    assert list(PROVIDERS) == [
        "ollama",
        "ollama_cloud",
        "openai",
        "anthropic",
        "gemini",
        "openai_compatible",
        "anthropic_compatible",
    ]
    for kind, info in PROVIDERS.items():
        assert info.kind == kind
        assert not info.default_base_url.endswith("/")
        # A provider that issues keys says where to get one.
        assert (info.api_key == "required") == (info.api_key_url is not None)


def test_environment_config_is_the_single_env_provider() -> None:
    config = environment_config(
        kind="ollama", base_url="http://localhost:11434/", model="gemma3", api_key=SecretStr("")
    )

    assert config.source == "environment"
    assert config.active_provider == ProviderConfig(
        "ollama", "http://localhost:11434", "gemma3", SecretStr("")
    )
    assert config.active_provider.protocol == "ollama"


def test_active_provider_must_have_settings() -> None:
    with pytest.raises(ValueError, match="has no settings"):
        LlmConfig(active="openai", providers={}, source="saved")


def test_connection_reuses_the_saved_key_for_the_same_url() -> None:
    connection = ProviderConnection(kind="anthropic", base_url=ANTHROPIC_URL)

    provider = resolve_connection(_saved(_anthropic()), connection, "claude-haiku-5-5")

    assert provider.api_key.get_secret_value() == LONG_KEY
    assert provider.model == "claude-haiku-5-5"


def test_saved_key_is_never_sent_to_another_url() -> None:
    connection = ProviderConnection(kind="anthropic", base_url="https://proxy.example")

    provider = resolve_connection(_saved(_anthropic()), connection)

    assert provider.api_key.get_secret_value() == ""


def test_saved_key_belongs_to_its_provider_only() -> None:
    connection = ProviderConnection(kind="gemini", base_url=ANTHROPIC_URL)

    assert resolve_connection(_saved(_anthropic()), connection).api_key.get_secret_value() == ""


def test_an_explicit_key_wins_over_the_saved_one() -> None:
    connection = ProviderConnection(kind="anthropic", base_url=ANTHROPIC_URL, api_key="new")

    assert resolve_connection(_saved(_anthropic()), connection).api_key.get_secret_value() == "new"


def test_saving_activates_the_provider_and_keeps_the_others() -> None:
    ollama = ProviderConfig("ollama", "http://localhost:11434", "gemma3", SecretStr(""))
    update = ProviderSettingsInput(
        kind="anthropic", base_url=ANTHROPIC_URL, model="claude-sonnet-5-5", api_key=None
    )

    config = with_provider(_saved(ollama, _anthropic()), update)

    assert config.active == "anthropic"
    assert config.source == "saved"
    assert config.providers["ollama"] == ollama
    assert config.providers["anthropic"].model == "claude-sonnet-5-5"
    assert config.providers["anthropic"].api_key.get_secret_value() == LONG_KEY


def test_environment_settings_are_not_copied_into_the_saved_file() -> None:
    environment = environment_config(
        kind="openai", base_url="https://api.openai.com/v1", model="m", api_key=SecretStr("env")
    )
    update = ProviderSettingsInput(kind="ollama", base_url="http://localhost:11434", model="m")

    config = with_provider(environment, update)

    assert list(config.providers) == ["ollama"]


def test_an_empty_key_removes_the_saved_one() -> None:
    update = ProviderSettingsInput(
        kind="anthropic_compatible", base_url="https://x.example", model="m", api_key=""
    )
    saved = ProviderConfig("anthropic_compatible", "https://x.example", "m", SecretStr("old"))

    config = with_provider(_saved(saved), update)

    assert config.active_provider.api_key.get_secret_value() == ""


def test_providers_that_need_a_key_cannot_be_saved_without_one() -> None:
    update = ProviderSettingsInput(kind="gemini", base_url="https://g.example", model="m")

    with pytest.raises(InvalidSettingsError, match="Google Gemini needs an API key"):
        with_provider(_saved(_anthropic()), update)


def test_view_never_contains_the_key() -> None:
    short = ProviderConfig("openai_compatible", "http://localhost:8080/v1", "m", SecretStr("short"))
    config = _saved(_anthropic(), short)

    view = to_view(config)

    assert LONG_KEY not in view.model_dump_json()
    assert "short" not in view.model_dump_json()
    by_kind = {p.kind: p for p in view.providers}
    assert by_kind["anthropic"].api_key_hint == "…abcd"
    assert by_kind["openai_compatible"].api_key_set is True
    assert by_kind["openai_compatible"].api_key_hint is None  # too short to hint safely


def test_view_lists_providers_in_catalogue_order() -> None:
    ollama = ProviderConfig("ollama", "http://localhost:11434", "gemma3", SecretStr(""))

    view = to_view(_saved(_anthropic(), ollama))

    assert [p.kind for p in view.providers] == ["ollama", "anthropic"]
    assert view.active == "anthropic"
    assert view.providers[0].api_key_set is False
