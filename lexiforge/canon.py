"""Frozen canonicalisation for term matching.

This module is the load-bearing part of scoring: every recall number depends on
it, so it is versioned, deterministic, and never edited after pass-2 data
exists. If a rule changes, ``CANON_VERSION`` changes and every prior score is
invalid.

The eight steps are applied in a fixed order. Each exists because of a concrete
failure it prevents, and each is covered by a test.

1. Unicode NFC                       precomposed vs decomposed accents
2. Nukta preserved                   क / क़ are contrastive, not equivalent
3. Chandrabindu -> anusvara          ASR alternates ँ / ं freely
4. No transliteration                Devanagari and Latin are separate namespaces
5. Latin casefold                    NACH / Nach / nach
6. Punctuation and hyphen handling   e-mandate vs e mandate; don't vs dont
7. Acronym spacing collapse          "N A C H" vs "NACH"
8. Digit shape only                  Devanagari digits -> ASCII; words never touch digits

Step 8 deliberately does NOT fold words to digits. "twenty" and "20" remain
distinct unless an explicit alias says otherwise.
"""

from __future__ import annotations

import re
import unicodedata

CANON_VERSION = "matcher-v1.0"

_APOSTROPHES = "'\u2018\u2019\u02bc`"
_DEVANAGARI_DIGITS = "०१२३४५६७८९"
_ASCII_DIGITS = "0123456789"
_DIGIT_TABLE = str.maketrans(_DEVANAGARI_DIGITS, _ASCII_DIGITS)

_APOSTROPHE_RE = re.compile(f"[{re.escape(_APOSTROPHES)}]")


def _is_punct_or_symbol(ch: str) -> bool:
    return unicodedata.category(ch)[0] in {"P", "S"}


def _step_punctuation(text: str) -> str:
    """Hyphens become spaces, apostrophes vanish, everything else spaces out.

    Why the asymmetry: ASR emits ``e-mandate`` and ``e mandate`` for the same
    speech, so a hyphen must be a separator. But ``don't`` and ``dont`` are the
    same word, so deleting the apostrophe is correct and spacing it would
    invent a token.
    """
    text = _APOSTROPHE_RE.sub("", text)
    chars = [" " if _is_punct_or_symbol(ch) else ch for ch in text]
    return "".join(chars)


def _step_acronyms(text: str) -> str:
    """Join runs of three or more single letters: ``n a c h`` -> ``nach``.

    Three is the floor because two-letter runs are usually real words or
    initials, and joining them would invent tokens. Runs longer than six are
    left alone as a guard against degenerate input.
    """
    tokens = text.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if len(token) == 1 and token.isalpha():
            j = i
            while j < len(tokens) and len(tokens[j]) == 1 and tokens[j].isalpha():
                j += 1
            run = tokens[i:j]
            if 3 <= len(run) <= 6:
                out.append("".join(run))
            else:
                out.extend(run)
            i = j
        else:
            out.append(token)
            i += 1
    return " ".join(out)


def canon(text: str) -> str:
    """Return the canonical matching key for ``text``.

    ``canon(a) == canon(b)`` means the two surfaces are the same term under the
    frozen rules. Nothing else about them is inferred: no edit distance, no
    phonetic comparison, no cross-script folding.
    """
    if text is None:
        raise TypeError("canon() received None")

    text = unicodedata.normalize("NFC", text)          # 1
    # 2: nukta is preserved; no rule touches U+093C.
    text = text.replace("\u0901", "\u0902")            # 3 chandrabindu -> anusvara
    # 4: no transliteration. Scripts stay in their own namespace.
    text = text.casefold()                             # 5
    text = _step_punctuation(text)                     # 6
    text = _step_acronyms(text)                        # 7
    text = text.translate(_DIGIT_TABLE)                # 8 digits only
    return " ".join(text.split())


def tokens(text: str) -> list[str]:
    """Canonicalised token list, for span-level matching."""
    return canon(text).split()
