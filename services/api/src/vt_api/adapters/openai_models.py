"""Readiness of an OpenAI-compatible model server (Speaches, Kokoro-FastAPI...): it answers
`/models` and lists the model we need."""

import openai

from vt_api.adapters.openai_chat import provider_error
from vt_contracts.speech import ModelStatus


def base_url(client: openai.AsyncOpenAI) -> str:
    return str(client.base_url).rstrip("/")


async def model_status(client: openai.AsyncOpenAI, model: str) -> ModelStatus:
    """Never raises: a failure is a status with the reason in `detail`."""
    url = base_url(client)
    status = ModelStatus(base_url=url, model=model, reachable=False, model_ready=False)
    try:
        models = [listed.id async for listed in client.models.list()]
    except openai.APIError as error:
        return status.model_copy(update={"detail": provider_error(error, url).message})
    if model not in models:
        return status.model_copy(
            update={"reachable": True, "detail": f"The model {model} is not downloaded."}
        )
    return status.model_copy(update={"reachable": True, "model_ready": True})
