"""`/v1/llm/*`: chat model providers, their settings, model lists and connection tests."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from vt_api.domain.llm import InvalidSettingsError, ProviderError
from vt_api.services.llm import LlmService
from vt_contracts.llm import (
    ConnectionTestRequest,
    ConnectionTestResult,
    LlmSettingsView,
    ModelList,
    ProblemDetail,
    ProviderConnection,
    ProviderInfo,
    ProviderSettingsInput,
)

router = APIRouter(prefix="/v1/llm", tags=["llm"])


def _llm_service(request: Request) -> LlmService:
    service: LlmService = request.app.state.container.llm
    return service


Llm = Annotated[LlmService, Depends(_llm_service)]


@router.get("/providers")
async def list_providers(llm: Llm) -> list[ProviderInfo]:
    """Every supported provider, in display order."""
    return llm.providers()


@router.get("/settings")
async def get_settings(llm: Llm) -> LlmSettingsView:
    return await llm.view()


@router.put(
    "/settings",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Incomplete settings"}},
)
async def save_settings(body: ProviderSettingsInput, llm: Llm) -> LlmSettingsView:
    """Save a provider's settings and make it the active one."""
    try:
        return await llm.save(body)
    except InvalidSettingsError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error


@router.delete("/settings")
async def reset_settings(llm: Llm) -> LlmSettingsView:
    """Forget the settings saved from the UI, API keys included; the environment applies."""
    return await llm.reset()


@router.post(
    "/models",
    responses={status.HTTP_502_BAD_GATEWAY: {"model": ProblemDetail}},
)
async def list_models(body: ProviderConnection, llm: Llm) -> ModelList:
    """The provider's models. POST because the body may carry an API key."""
    try:
        return ModelList(models=await llm.list_models(body))
    except ProviderError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, error.message) from error


@router.post("/test")
async def test_connection(body: ConnectionTestRequest, llm: Llm) -> ConnectionTestResult:
    """Ask the model for one short sentence and time it."""
    return await llm.test(body)
