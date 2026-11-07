"""Parity guards: ``_tokenize_with_spans`` must mirror the frozen canonicaliser.

Every raw surface must tokenise to exactly the keys :func:`lexiforge.canon.tokens`
produces, while the returned offsets still index the *original* string so that
``text[start:end]`` is the raw surface.

The ``apostrophe-*combining`` cases pin a real drift that was found by probing:
the tokenizer used to delete apostrophes before calling ``canon()`` per chunk,
so the chunk was re-NFC'd across the deleted apostrophe while ``canon()``
normalises the whole string *before* deleting apostrophes. ``"a'\\u0301"``
therefore produced ``"\\u00e1"`` instead of canon's ``"a\\u0301"``.
"""

import unicodedata

import pytest

from lexiforge.canon import canon, tokens
from lexiforge.score.match import _tokenize_with_spans

CASES = [
    ("nfc-decomposed", "cafe\u0301"),
    ("nfc-multiple-accents", "A\u030angstro\u0308m"),
    ("nukta-decomposed", "\u0915\u093c"),
    ("nukta-precomposed", "\u0958"),
    ("nukta-word", "\u0915\u093c\u093e\u0924\u093e"),
    ("chandrabindu", "\u0939\u0942\u0901"),
    ("anusvara", "\u0939\u0942\u0902"),
    ("apostrophe-straight", "don't"),
    ("apostrophe-right-single", "don\u2019t"),
    ("apostrophe-modifier-letter", "don\u02bct"),
    ("apostrophe-backtick", "don`t"),
    ("apostrophe-absent", "dont"),
    ("hyphen", "e-mandate"),
    ("en-dash", "e\u2013mandate"),
    ("em-dash", "e\u2014mandate"),
    ("acronym-3", "u p i"),
    ("acronym-4", "n a c h"),
    ("acronym-5", "g s t i n"),
    ("acronym-6", "g s t i n x"),
    ("acronym-2", "e a"),
    ("acronym-7", "a b c d e f g"),
    ("acronym-dotted", "N.A.C.H."),
    ("acronym-apostrophes", "n'a'c'h"),
    ("devanagari-digits", "\u0968\u0966\u0966\u0966"),
    ("ascii-digits", "2000"),
    ("digits-and-word", "20 rupaye"),
    ("mixed-script", "\u0916\u093e\u0924\u093e khata"),
    ("multiple-spaces", "a   b    c"),
    ("punctuation-run", "pay!!! ...now???"),
    ("punctuation-breaks-acronym", "n a c h- u p i"),
    ("apostrophe-then-combining", "a'\u0301"),
    ("curly-apostrophe-then-combining", "e\u2019\u0301"),
    ("marks-apostrophe-reorder", "\u0301'\u093c"),
    ("devanagari-apostrophe-nukta", "\u0915'\u093c"),
    ("chandrabindu-after-apostrophe", "\u0939'\u0901"),
    ("empty", ""),
    ("whitespace-only", "   \t\n "),
]

TEXTS = [text for _, text in CASES]
IDS = [name for name, _ in CASES]


def _is_content(ch: str) -> bool:
    """Characters that must be inside some token (boundaries are excluded)."""
    return not ch.isspace() and unicodedata.category(ch)[0] not in {"P", "S"}


@pytest.mark.parametrize("text", TEXTS, ids=IDS)
def test_token_keys_equal_canonical_tokens(text):
    keys = [key for key, _, _ in _tokenize_with_spans(text)]
    assert keys == tokens(text)


@pytest.mark.parametrize("text", TEXTS, ids=IDS)
def test_surfaces_reconstruct_the_raw_text(text):
    for key, start, end in _tokenize_with_spans(text):
        surface = text[start:end]
        assert surface, f"empty surface at ({start}, {end})"
        assert canon(surface) == key, (
            f"surface {surface!r} canonicalises to {canon(surface)!r}, not {key!r}"
        )


@pytest.mark.parametrize("text", TEXTS, ids=IDS)
def test_offsets_are_ordered_disjoint_and_cover_content(text):
    toks = _tokenize_with_spans(text)
    covered: set[int] = set()
    prev_end = 0
    for _, start, end in toks:
        assert 0 <= start < end <= len(text)
        assert start >= prev_end, "spans must be ordered and non-overlapping"
        prev_end = end
        covered.update(range(start, end))
    content = {i for i, ch in enumerate(text) if _is_content(ch)}
    assert content <= covered, "content characters must belong to a token span"
