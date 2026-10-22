import pytest

from vt_api.realtime.sentences import SentenceSplitter, speakable


def _split(*chunks: str) -> list[str]:
    splitter = SentenceSplitter()
    sentences = [sentence for chunk in chunks for sentence in splitter.feed(chunk)]
    return sentences + splitter.flush()


def test_sentences_come_out_as_soon_as_they_end() -> None:
    splitter = SentenceSplitter()

    assert splitter.feed("Nice") == []
    assert splitter.feed("! What did") == ["Nice!"]
    assert splitter.feed(" you do?") == []  # could still be "?!" or a closing quote
    assert splitter.feed(" Tell me.") == ["What did you do?"]
    assert splitter.flush() == ["Tell me."]
    assert splitter.flush() == []


@pytest.mark.parametrize(
    ("chunks", "sentences"),
    [
        (("Really?! Wow. ",), ["Really?!", "Wow."]),
        (('He said "hi." Then ', "he left."), ['He said "hi."', "Then he left."]),
        (("It costs 3.", "5 euros. OK"), ["It costs 3.5 euros.", "OK"]),
        (("Ask Mr. Brown, e.g. ", "today. Yes"), ["Ask Mr. Brown, e.g. today.", "Yes"]),
        (("Well...", " maybe"), ["Well...", "maybe"]),
        (("First line\n\nSecond line",), ["First line", "Second line"]),
        (("\nHello. ",), ["Hello."]),
        (("**Great!** Now ", "you."), ["**Great!**", "Now you."]),
        (("   ",), []),
    ],
)
def test_where_sentences_end(chunks: tuple[str, ...], sentences: list[str]) -> None:
    assert _split(*chunks) == sentences


@pytest.mark.parametrize(
    ("sentence", "spoken"),
    [
        ("**Great** job!", "Great job!"),
        ("# Tips:  `be`  and _do_", "Tips: be and do"),
        ("Well done 👏 Ana!", "Well done Ana!"),
        ("...", None),
        ("🙂", None),
    ],
)
def test_speakable(sentence: str, spoken: str | None) -> None:
    assert speakable(sentence) == spoken
