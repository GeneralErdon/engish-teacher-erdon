import json

import pytest

from vt_api.domain.llm import ChatMessage
from vt_api.teacher.conversation import correction_messages, reply_messages
from vt_api.teacher.corrections import CorrectionParseError, normalise, parse_correction
from vt_contracts.learner import LearnerProfile
from vt_contracts.ws import CorrectionItem

B1_NATIVE = LearnerProfile(level="B1", explanations="native")
C1_ENGLISH = LearnerProfile(level="C1", explanations="english")
ORIGINAL = "yesterday I have went to the beach"


def test_reply_prompt_carries_the_level_then_the_history() -> None:
    history = [ChatMessage("user", "Hi!")]

    messages = reply_messages(history, B1_NATIVE)

    assert messages[0].role == "system"
    assert "level is B1" in messages[0].content
    assert "topic" not in messages[0].content
    assert messages[1:] == history


def test_reply_prompt_can_set_a_topic() -> None:
    system = reply_messages([], B1_NATIVE, topic="travel")[0].content

    assert system.endswith("Today's topic: travel.")


def test_corrections_are_explained_in_the_native_language_by_default() -> None:
    system, user = correction_messages(ORIGINAL, B1_NATIVE, "es")

    assert "ISO 639 code `es`" in system.content
    assert "naturalness" not in system.content.split("Reply with JSON")[0]
    assert user == ChatMessage("user", ORIGINAL)


def test_advanced_learners_get_english_and_naturalness() -> None:
    system = correction_messages(ORIGINAL, C1_ENGLISH, "es")[0].content

    assert "in English" in system
    assert "phrasing a native speaker would not use" in system


def _item(**overrides: str) -> dict[str, str]:
    item = {
        "original": "have went",
        "suggestion": "went",
        "kind": "grammar",
        "explanation": "Pasado simple.",
    }
    return item | overrides


def _answer(corrected: str, *items: dict[str, str]) -> str:
    return json.dumps({"corrected": corrected, "items": list(items)})


def test_parses_a_correction() -> None:
    corrected, items = parse_correction(_answer("Yesterday I went to the beach", _item()), ORIGINAL)

    assert corrected == "Yesterday I went to the beach"
    assert items == [
        CorrectionItem(
            original="have went", suggestion="went", kind="grammar", explanation="Pasado simple."
        )
    ]


def test_tolerates_fences_and_chatter_around_the_json() -> None:
    raw = f"Sure! Here you go:\n```json\n{_answer('Yesterday I went', _item())}\n```"

    corrected, items = parse_correction(raw, ORIGINAL)

    assert corrected == "Yesterday I went"
    assert len(items) == 1


def test_unknown_kinds_become_grammar_and_no_op_items_are_dropped() -> None:
    raw = _answer(
        "Yesterday I went to the beach",
        _item(kind="tense"),
        _item(original="Beach.", suggestion="beach"),
    )

    _, items = parse_correction(raw, ORIGINAL)

    assert [item.kind for item in items] == ["grammar"]


@pytest.mark.parametrize(
    "raw",
    [
        _answer("Yesterday, I have went to the beach."),  # only punctuation changed
        _answer("Yesterday I went to the beach"),  # changed but no items
        _answer(ORIGINAL, _item()),  # items but nothing changed
    ],
)
def test_nothing_to_fix_keeps_the_original(raw: str) -> None:
    assert parse_correction(raw, ORIGINAL) == (ORIGINAL, [])


@pytest.mark.parametrize("raw", ["no json here", "{not: json}", '{"items": []}', "} backwards {"])
def test_unusable_answers_raise(raw: str) -> None:
    with pytest.raises(CorrectionParseError):
        parse_correction(raw, ORIGINAL)


def test_normalise_ignores_case_and_punctuation() -> None:
    assert normalise("  I'm FINE, thanks!! ") == "i'm fine thanks"
