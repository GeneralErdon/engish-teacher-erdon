"""Turns the model's correction JSON into validated `CorrectionItem`s.

Models do not always follow the format: code fences, text around the JSON, unknown kinds or
"corrections" that change nothing. Parse leniently, validate strictly, and fail loudly
(`CorrectionParseError`) when nothing usable is left.
"""

import json
import re
from typing import cast, get_args

from pydantic import BaseModel, ValidationError

from vt_contracts.ws import CorrectionItem, CorrectionKind

_KINDS: frozenset[str] = frozenset(get_args(CorrectionKind.__value__))
_NOT_WORD = re.compile(r"[^\w']+")


class CorrectionParseError(ValueError):
    """The model's answer held no usable correction JSON."""


class _RawItem(BaseModel):
    original: str
    suggestion: str
    kind: str = "grammar"
    explanation: str = ""


class _RawCorrection(BaseModel):
    corrected: str
    items: list[_RawItem] = []


def _kind(value: str) -> CorrectionKind:
    return cast("CorrectionKind", value) if value in _KINDS else "grammar"


def normalise(text: str) -> str:
    """Lower case, words only: capitalisation and punctuation are not mistakes here."""
    return " ".join(_NOT_WORD.sub(" ", text.lower()).split())


def _json_object(raw: str) -> str:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end < start:
        msg = "no JSON object in the model's answer"
        raise CorrectionParseError(msg)
    return raw[start : end + 1]


def parse_correction(raw: str, original: str) -> tuple[str, list[CorrectionItem]]:
    """`(corrected, items)` for `original`. No items means nothing to fix."""
    try:
        parsed = _RawCorrection.model_validate(json.loads(_json_object(raw)))
    except (json.JSONDecodeError, ValidationError) as error:
        msg = "the model's correction JSON is invalid"
        raise CorrectionParseError(msg) from error

    items = [
        CorrectionItem(
            original=item.original.strip(),
            suggestion=item.suggestion.strip(),
            kind=_kind(item.kind),
            explanation=item.explanation.strip(),
        )
        for item in parsed.items
        if normalise(item.original) != normalise(item.suggestion)
    ]
    corrected = parsed.corrected.strip()
    if not items or normalise(corrected) == normalise(original):
        return original, []
    return corrected, items
