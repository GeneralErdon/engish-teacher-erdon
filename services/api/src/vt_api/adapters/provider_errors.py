"""Turns HTTP failures from any provider into `ProviderError`s a user can act on."""

from vt_api.domain.llm import ProviderError

_MAX_DETAIL_CHARS = 300


def from_status(status: int, detail: str) -> ProviderError:
    detail = detail.strip()[:_MAX_DETAIL_CHARS]
    match status:
        case 401 | 403:
            return ProviderError("auth", f"The provider rejected the API key (HTTP {status}).")
        case 404:
            return ProviderError(
                "not_found", "Not found (HTTP 404): check the base URL and the model name."
            )
        case 429:
            return ProviderError(
                "rate_limited", "Rate limit or quota reached (HTTP 429). Try again later."
            )
        case _ if status < 500:
            return ProviderError("bad_request", f"The provider refused the request: {detail}")
        case _:
            return ProviderError("unavailable", f"The provider failed (HTTP {status}): {detail}")


def connection_failed(base_url: str) -> ProviderError:
    return ProviderError("connection", f"Could not connect to {base_url}.")


def timed_out(base_url: str) -> ProviderError:
    return ProviderError("connection", f"{base_url} did not answer in time.")
