import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.compose import highlight_entities, split_balanced


def _words(text):
    return set(re.findall(r"\S+", text))


def test_parts_one_returns_input_unchanged():
    text = "  hello world  "
    assert split_balanced(text, 1) == [text.strip()]


def test_never_cuts_mid_word():
    text = ("Play long-term games with long-term people. " * 10).strip()
    chunks = split_balanced(text, 3)
    for chunk in chunks:
        assert not chunk[:1].isspace()
        assert not chunk[-1:].isspace()
    assert _words(" ".join(chunks)) <= _words(text)


def test_prefers_paragraph_over_word_break_even_when_farther():
    prefix = "a" * 43 + "\n\n"  # paragraph boundary ends at index 45
    mid = "b" * 5 + " "  # word boundary ends at index 51
    suffix = "c" * 44
    text = prefix + mid + suffix  # length 95, target for parts=2 is 47.5

    chunks = split_balanced(text, 2)

    assert chunks[0] == "a" * 43
    assert chunks[1] == "b" * 5 + " " + "c" * 44


def test_prefers_sentence_over_word_break_even_when_farther():
    prefix = "a" * 40 + ". "  # sentence boundary ends at index 42
    mid = "b" * 5 + " "  # word boundary ends at index 48
    suffix = "c" * 44
    text = prefix + mid + suffix  # length 91, target for parts=2 is 45.5

    chunks = split_balanced(text, 2)

    assert chunks[0] == "a" * 40 + "."
    assert chunks[1] == "b" * 5 + " " + "c" * 44


def test_reassembles_to_original_modulo_whitespace():
    text = "One two three four five six seven eight nine ten eleven twelve."
    chunks = split_balanced(text, 3)
    normalized_original = re.sub(r"\s+", " ", text).strip()
    normalized_joined = re.sub(r"\s+", " ", " ".join(chunks)).strip()
    assert normalized_joined == normalized_original


def test_no_whitespace_does_not_crash():
    text = "a" * 500
    chunks = split_balanced(text, 3)
    assert "".join(chunks) != ""


def test_highlight_escapes_script_tag():
    out = highlight_entities("<script>alert(1)</script>", "#5eaee0")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_highlight_wraps_mention_hashtag_and_link():
    out = highlight_entities("hi @naval check #stoicism at https://example.com/x?y=1&z=2", "#5eaee0")
    assert out.count('<span class="ent"') == 3
    assert "&amp;" in out  # the & inside the URL query is still escaped
