"""Chat model providers: the catalogue of presets and the rules for their settings.

Pure: no I/O. Adapters speak the wire protocols (`vt_api.adapters`), the repository stores the
settings, and `vt_api.services.llm` ties them together.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import SecretStr

from vt_contracts.llm import (
    LlmSettingsView,
    ProviderConnection,
    ProviderInfo,
    ProviderKind,
    ProviderSettingsInput,
    ProviderSettingsView,
    WireProtocol,
)

PROVIDERS: Mapping[ProviderKind, ProviderInfo] = {
    info.kind: info
    for info in (
        ProviderInfo(
            kind="ollama",
            label="Ollama",
            description="Open models running on this computer with Ollama. Free and private.",
            protocol="ollama",
            default_base_url="http://localhost:11434",
            base_url_hint="From the Docker api, use http://host.docker.internal:11434",
            api_key="optional",
            api_key_url=None,
            suggested_model="",
        ),
        ProviderInfo(
            kind="ollama_cloud",
            label="Ollama Cloud",
            description="Large open models hosted by Ollama. Free tier with usage limits.",
            protocol="ollama",
            default_base_url="https://ollama.com",
            base_url_hint="https://ollama.com",
            api_key="required",
            api_key_url="https://ollama.com/settings/keys",
            suggested_model="",
        ),
        ProviderInfo(
            kind="openai",
            label="OpenAI",
            description="GPT models through the OpenAI API. Paid per token.",
            protocol="openai",
            default_base_url="https://api.openai.com/v1",
            base_url_hint="Ends in /v1",
            api_key="required",
            api_key_url="https://platform.openai.com/api-keys",
            suggested_model="",
        ),
        ProviderInfo(
            kind="anthropic",
            label="Anthropic",
            description="Claude models through the Anthropic API. Paid per token.",
            protocol="anthropic",
            default_base_url="https://api.anthropic.com",
            base_url_hint="Without /v1",
            api_key="required",
            api_key_url="https://platform.claude.com/settings/keys",
            suggested_model="claude-opus-5-5",
        ),
        ProviderInfo(
            kind="gemini",
            label="Google Gemini",
            description="Gemini models through Google AI Studio. Free tier with usage limits.",
            protocol="openai",
            default_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            base_url_hint="Gemini's OpenAI-compatible endpoint",
            api_key="required",
            api_key_url="https://aistudio.google.com/apikey",
            suggested_model="gemini-3.8-flash",
        ),
        ProviderInfo(
            kind="openai_compatible",
            label="OpenAI-compatible",
            description=(
                "Any server that speaks the OpenAI Chat Completions API: llama.cpp, LM Studio, "
                "vLLM, OpenRouter, Groq..."
            ),
            protocol="openai",
            default_base_url="",
            base_url_hint="Usually ends in /v1, e.g. http://localhost:1234/v1 for LM Studio",
            api_key="optional",
            api_key_url=None,
            suggested_model="",
        ),
        ProviderInfo(
            kind="anthropic_compatible",
            label="Anthropic-compatible",
            description="Any server that speaks the Anthropic Messages API.",
            protocol="anthropic",
            default_base_url="",
            base_url_hint="The base URL the provider gives for Anthropic clients, without /v1",
            api_key="optional",
            api_key_url=None,
            suggested_model="",
        ),
    )
}
"""Every preset, in the order the settings screen lists them."""

_KEY_HINT_MIN_LENGTH = 12
"""Shorter keys get no hint: four characters of a short key reveal too much of it."""


class InvalidSettingsError(ValueError):
    """Settings the user tried to save are incomplete (e.g. a required key is missing)."""


type ProviderErrorReason = Literal[
    "auth", "not_found", "rate_limited", "bad_request", "unavailable", "connection"
]


class ProviderError(Exception):
    """A provider call failed. `message` is safe to show to the user (it never holds a key)."""

    def __init__(self, reason: ProviderErrorReason, message: str) -> None:
        super().__init__(message)
        self.reason: ProviderErrorReason = reason
        self.message = message


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """How to reach one provider. `model` may be empty when only listing models."""

    kind: ProviderKind
    base_url: str
    model: str
    api_key: SecretStr

    @property
    def protocol(self) -> WireProtocol:
        return PROVIDERS[self.kind].protocol


@dataclass(frozen=True, slots=True)
class LlmConfig:
    """The active provider plus every provider the user has configured."""

    active: ProviderKind
    providers: Mapping[ProviderKind, ProviderConfig]
    source: Literal["environment", "saved"]

    def __post_init__(self) -> None:
        if self.active not in self.providers:
            msg = f"active provider {self.active!r} has no settings"
            raise ValueError(msg)

    @property
    def active_provider(self) -> ProviderConfig:
        return self.providers[self.active]


def environment_config(
    *, kind: ProviderKind, base_url: str, model: str, api_key: SecretStr
) -> LlmConfig:
    """The `VT_LLM_*` variables as a config: what applies until the user saves from the UI."""
    provider = ProviderConfig(kind, base_url.rstrip("/"), model, api_key)
    return LlmConfig(active=kind, providers={kind: provider}, source="environment")


def _saved_key(current: LlmConfig, connection: ProviderConnection) -> SecretStr:
    """The saved key for this provider, but only if it was saved for this same URL.

    A key must never be sent to a server it was not entered for: changing the URL drops it.
    """
    saved = current.providers.get(connection.kind)
    if saved is None or saved.base_url != connection.base_url:
        return SecretStr("")
    return saved.api_key


def resolve_connection(
    current: LlmConfig, connection: ProviderConnection, model: str = ""
) -> ProviderConfig:
    """What to call for a models list or a connection test, filling in the saved key."""
    api_key = (
        _saved_key(current, connection)
        if connection.api_key is None
        else SecretStr(connection.api_key)
    )
    return ProviderConfig(connection.kind, connection.base_url, model, api_key)


def with_provider(current: LlmConfig, update: ProviderSettingsInput) -> LlmConfig:
    """`current` with `update` saved and made the active provider.

    Settings that came from the environment are not copied into the saved file: environment
    secrets stay in the environment.
    """
    provider = resolve_connection(current, update, update.model)
    if PROVIDERS[update.kind].api_key == "required" and not provider.api_key.get_secret_value():
        label = PROVIDERS[update.kind].label
        msg = f"{label} needs an API key."
        raise InvalidSettingsError(msg)

    kept = current.providers if current.source == "saved" else {}
    return LlmConfig(
        active=update.kind,
        providers={**kept, update.kind: provider},
        source="saved",
    )


def _key_hint(api_key: SecretStr) -> str | None:
    secret = api_key.get_secret_value()
    return f"…{secret[-4:]}" if len(secret) >= _KEY_HINT_MIN_LENGTH else None


def to_view(config: LlmConfig) -> LlmSettingsView:
    """The settings as the UI sees them: no keys, providers in catalogue order."""
    providers = [
        ProviderSettingsView(
            kind=kind,
            base_url=provider.base_url,
            model=provider.model,
            api_key_set=bool(provider.api_key.get_secret_value()),
            api_key_hint=_key_hint(provider.api_key),
        )
        for kind in PROVIDERS
        if (provider := config.providers.get(kind)) is not None
    ]
    return LlmSettingsView(active=config.active, source=config.source, providers=providers)
