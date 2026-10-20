import pytest
from pydantic import ValidationError

from vt_contracts.health import HealthResponse


def test_round_trips_through_json() -> None:
    health = HealthResponse(status="ok", service="api", version="0.1.0")

    assert HealthResponse.model_validate_json(health.model_dump_json()) == health


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({"status": "ok", "service": "api", "version": "1", "x": 1})
