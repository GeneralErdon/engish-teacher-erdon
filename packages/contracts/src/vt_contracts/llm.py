"""Chat model (LLM) provider settings: the `/v1/llm/*` REST API between the UI and `api`.

API keys travel only from the UI to the api (`ProviderSettingsInput`, `ProviderConnection`).
Nothing the api returns ever contains one: `ProviderSettingsView` says whether a key is saved
and shows its last characters.
"""

from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    WithJsonSchema,
)

type ProviderKind = Literal[
    "ollama",
    "ollama_cloud",
    "openai",
    "anthropic",
    "gemini",
    "openai_compatible",
    "anthropic_compatible",
]
"""A preset: which wire protocol to speak, the default URL, and whether a key is needed."""

type WireProtocol = Literal["openai", "ollama", "anthropic"]
"""`openai`: Chat Completions. `ollama`: Chat Completions under `/v1` plus Ollama's model list.
`anthropic`: the Messages API."""

type ApiKeyPolicy = Literal["required", "optional"]


_HTTP_URL: TypeAdapter[AnyHttpUrl] = TypeAdapter(AnyHttpUrl)


def _http_url(value: str) -> str:
    return str(_HTTP_URL.validate_python(value)).rstrip("/")


BaseUrl = Annotated[
    str,
    AfterValidator(_http_url),
    WithJsonSchema({"type": "string", "format": "uri", "minLength": 1, "maxLength": 2083}),
]
"""An http(s) URL, stored without a trailing slash."""

ModelName = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^\S+$")]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProviderInfo(_Frozen):
    """One entry of `GET /v1/llm/providers`: what the settings form needs to render a preset."""

    kind: ProviderKind
    label: str
    description: str
    protocol: WireProtocol
    default_base_url: str
    """Empty when the user must type it (custom endpoints)."""
    base_url_hint: str
    api_key: ApiKeyPolicy
    api_key_url: str | None
    """Where to create a key, if the provider issues them."""
    suggested_model: str
    """A sensible first choice; empty when it depends on what the user has installed."""


class ProviderSettingsView(_Frozen):
    """A provider's saved settings, without the key."""

    kind: ProviderKind
    base_url: str
    model: str
    api_key_set: bool
    api_key_hint: str | None
    """Last characters of the saved key (`…a1b2`), so the user can tell keys apart."""


class LlmSettingsView(_Frozen):
    """Body of `GET`/`PUT /v1/llm/settings`."""

    active: ProviderKind
    source: Literal["environment", "saved"]
    """`environment`: nothing saved from the UI yet, the `VT_LLM_*` variables apply."""
    providers: list[ProviderSettingsView]
    """Every provider with settings: the active one plus any saved earlier."""


class ProviderConnection(_Frozen):
    """Enough to reach a provider: body of `POST /v1/llm/models`."""

    kind: ProviderKind
    base_url: BaseUrl
    api_key: str | None = Field(default=None, max_length=500)
    """`None` reuses the saved key, but only if it was saved for this same `base_url`."""


class ProviderSettingsInput(ProviderConnection):
    """Body of `PUT /v1/llm/settings`: save this provider and make it the active one.

    `api_key`: `None` keeps the saved key, `""` removes it, anything else replaces it.
    """

    model: ModelName


class ConnectionTestRequest(ProviderConnection):
    """Body of `POST /v1/llm/test`."""

    model: ModelName


class ModelList(_Frozen):
    """Body of `POST /v1/llm/models`: model ids exactly as the provider expects them, sorted."""

    models: list[str]


class ConnectionTestResult(_Frozen):
    """Body of `POST /v1/llm/test`. A failed test is a normal result (`ok=False`), not an error."""

    ok: bool
    latency_ms: int | None = None
    """Time to the complete reply."""
    reply: str | None = None
    error: str | None = None


class ProblemDetail(_Frozen):
    """Error body (`{"detail": ...}`), as FastAPI's `HTTPException` renders it."""

    detail: str
