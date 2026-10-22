"""Cut a streamed reply into sentences, so each is spoken while the rest is still generated.

The tutor starts talking once its first sentence is complete, not after the whole reply.
"""

import re
import unicodedata

_END = re.compile(r"""[.!?…]+["')\]*_]*\s+|\n+""")
"""Terminal punctuation (plus closing quotes, brackets or Markdown emphasis) followed by
whitespace, or a line break. Requiring the whitespace keeps "3.5" whole until more text
arrives."""

_ABBREVIATIONS = frozenset({"mr.", "mrs.", "ms.", "dr.", "st.", "vs.", "e.g.", "i.e."})
"""Words whose full stop does not end the sentence."""

_MARKUP = re.compile(r"[*_#`~]+")


class SentenceSplitter:
    def __init__(self) -> None:
        self._pending = ""

    def feed(self, text: str) -> list[str]:
        """Add streamed text; return the sentences it completed."""
        self._pending += text
        sentences: list[str] = []
        start = 0
        for match in _END.finditer(self._pending):
            sentence = self._pending[start : match.end()].strip()
            if not sentence or sentence.split()[-1].lower() in _ABBREVIATIONS:
                continue
            sentences.append(sentence)
            start = match.end()
        self._pending = self._pending[start:]
        return sentences

    def flush(self) -> list[str]:
        """What is left once the reply is complete."""
        rest, self._pending = self._pending.strip(), ""
        return [rest] if rest else []


def speakable(sentence: str) -> str | None:
    """`sentence` without Markdown or symbols such as emoji, or `None` when nothing is left to
    say ("...")."""
    words = "".join(char for char in sentence if unicodedata.category(char) != "So")
    text = " ".join(_MARKUP.sub("", words).split())
    return text if any(char.isalnum() for char in text) else None
