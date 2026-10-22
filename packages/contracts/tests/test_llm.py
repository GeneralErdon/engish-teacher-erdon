import pytest
from pydantic import ValidationError

from vt_contracts.llm import ConnectionTestRequest, ProviderConnection, ProviderSettingsInput


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("https://api.openai.com/v1/", "https://api.openai.com/v1"),
        ("http://localhost:11434", "http://localhost:11434"),
        ("https://ollama.com/", "https://ollama.com"),
    ],
)
def test_base_url_is_stored_without_a_trailing_slash(given: str, stored: str) -> None:
    connection = ProviderConnection(kind="openai", base_url=given)

    assert connection.base_url == stored


@pytest.mark.parametrize("url", ["", "ftp://example.com", "not a url", "localhost:11434"])
def test_base_url_must_be_http(url: str) -> None:
    with pytest.raises(ValidationError):
        ProviderConnection(kind="ollama", base_url=url)


def test_api_key_defaults_to_reusing_the_saved_one() -> None:
    connection = ProviderConnection(kind="anthropic", base_url="https://api.anthropic.com")

    assert connection.api_key is None


@pytest.mark.parametrize("model", ["", "has spaces", "x" * 201])
def test_model_name_is_one_non_empty_token(model: str) -> None:
    with pytest.raises(ValidationError):
        ProviderSettingsInput(kind="gemini", base_url="https://example.com", model=model)


def test_test_request_needs_a_model() -> None:
    with pytest.raises(ValidationError):
        ConnectionTestRequest.model_validate({"kind": "openai", "base_url": "https://x.example"})


def test_rejects_unknown_fields_and_kinds() -> None:
    with pytest.raises(ValidationError):
        ProviderConnection.model_validate(
            {"kind": "openai", "base_url": "https://x.example", "extra": 1}
        )
    with pytest.raises(ValidationError):
        ProviderConnection.model_validate({"kind": "mistral", "base_url": "https://x.example"})
