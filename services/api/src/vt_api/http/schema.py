"""The OpenAPI document, plus the WebSocket events (`vt_contracts.ws`), which OpenAPI has no
way to describe. Adding them as components gives the UI generated types for both.

Serialization mode: fields with defaults (`type`, `v`) are required in the generated types, as
they are on the wire."""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import TypeAdapter

from vt_contracts.ws import CLIENT_EVENT, SERVER_EVENT

_REF = "#/components/schemas/{model}"
_EVENTS: dict[str, TypeAdapter[Any]] = {"ClientEvent": CLIENT_EVENT, "ServerEvent": SERVER_EVENT}


def openapi_with_events(app: FastAPI) -> dict[str, Any]:
    if app.openapi_schema is None:
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        components: dict[str, Any] = schema.setdefault("components", {}).setdefault("schemas", {})
        for name, adapter in _EVENTS.items():
            union = adapter.json_schema(ref_template=_REF, mode="serialization")
            components.update(union.pop("$defs", {}))
            components[name] = union
        app.openapi_schema = schema
    return app.openapi_schema
