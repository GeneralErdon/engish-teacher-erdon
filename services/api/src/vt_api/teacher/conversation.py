"""The tutor's side of the conversation: prompts for replies and for corrections."""

from collections.abc import Sequence

from vt_api.domain.llm import ChatMessage
from vt_api.teacher import prompts
from vt_contracts.learner import LearnerProfile

ADVANCED_LEVELS = frozenset({"B2", "C1", "C2"})


def reply_messages(
    history: Sequence[ChatMessage], profile: LearnerProfile, topic: str | None = None
) -> list[ChatMessage]:
    """The system prompt for `profile`, then the conversation so far."""
    system = prompts.CONVERSATION.substitute(
        level=profile.level,
        topic=prompts.TOPIC.substitute(topic=topic) if topic else "",
    )
    return [ChatMessage("system", system), *history]


def correction_messages(
    text: str, profile: LearnerProfile, native_language: str
) -> list[ChatMessage]:
    """Ask for corrections of one learner message, explained in the chosen language."""
    language = (
        "English"
        if profile.explanations == "english"
        else f"the learner's native language (ISO 639 code `{native_language}`)"
    )
    system = prompts.CORRECTIONS.substitute(
        level=profile.level,
        language=language,
        naturalness=prompts.NATURALNESS if profile.level in ADVANCED_LEVELS else "",
    )
    return [ChatMessage("system", system), ChatMessage("user", text)]
