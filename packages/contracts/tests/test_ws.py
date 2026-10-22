import pytest
from pydantic import ValidationError

from vt_contracts.ws import (
    CLIENT_EVENT,
    SERVER_EVENT,
    Correction,
    CorrectionItem,
    InputText,
    SessionStart,
)


def test_client_events_are_told_apart_by_type() -> None:
    event = CLIENT_EVENT.validate_json('{"type": "input.text", "v": 1, "text": "Hi"}')

    assert event == InputText(text="Hi")


def test_version_and_type_default_on_the_way_out() -> None:
    assert SessionStart().model_dump() == {"v": 1, "type": "session.start", "topic": None}


@pytest.mark.parametrize(
    "raw",
    [
        '{"type": "input.text", "v": 2, "text": "Hi"}',
        '{"type": "input.text", "v": 1, "text": ""}',
        '{"type": "input.audio", "v": 1}',
        '{"type": "session.start", "v": 1, "extra": true}',
    ],
)
def test_rejects_invalid_client_events(raw: str) -> None:
    with pytest.raises(ValidationError):
        CLIENT_EVENT.validate_json(raw)


def test_server_events_round_trip() -> None:
    correction = Correction(
        turn_id="t1",
        corrected="I went home",
        items=[
            CorrectionItem(
                original="have went", suggestion="went", kind="grammar", explanation="Past simple."
            )
        ],
        latency_ms=900,
    )

    assert SERVER_EVENT.validate_json(correction.model_dump_json()) == correction
