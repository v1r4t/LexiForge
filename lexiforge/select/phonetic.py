"""HING-SKEL: deterministic Hinglish consonant skeleton for term selection.

The skeleton is a coarse phonetic key over romanised banking terms. It
deliberately over-merges spelling variants (aspiration, soft/hard ``c``,
short vowels, nasals) so pass-1 ASR hypotheses can match glossary terms
they sound like. It never decides a match on its own: the selector pairs
it with veto rules (:func:`is_hard_negative_pair`) that stop it merging
pre-registered confusable pairs.

Pipeline (fixed order, stdlib only, seeded from
:func:`lexiforge.canon.canon`):

1. Canonicalise with :func:`~lexiforge.canon.canon` — lowercase,
   punctuation stripped, ``e-mandate`` split, letter-spelled acronyms
   joined (``i f s c`` -> ``ifsc``).
2. Roman-Hindi: ``ph`` -> ``f``; ``v`` <-> ``w`` (swap; step 4 folds both
   to ``v``); ``q`` -> ``k``; ``z`` -> ``j``; ``x`` -> ``ks``; ``c`` ->
   ``k`` before ``a``/``o``/``u``, keeping ``ch`` intact for step 3.
3. Aspiration collapse: ``kh`` -> ``k``, ``gh`` -> ``g``, ``ch`` -> ``c``,
   ``jh`` -> ``j``, ``th`` -> ``t``, ``dh`` -> ``d``, ``ph`` -> ``p``,
   ``bh`` -> ``b``. (``ph`` is already ``f`` after step 2, so that rule
   is a deterministic no-op retained for completeness.)
4. Coronal/continuant merge: ``sh`` -> ``s``; soft ``c`` (before
   ``e``/``i``/``y``) -> ``s``, remaining ``c`` -> ``k`` (covers
   word-final ``c`` as in ``micr`` and English ``ck`` via geminate
   collapse); ``d`` -> ``t`` (retroflex/dental voicing merge; ``n`` stays
   distinct so step 6 has a nasal class to normalise); ``y`` -> ``i``;
   ``w`` -> ``v``.
5. Vowel compression per word: ``aa`` -> ``a``, ``ee`` -> ``i``,
   ``oo`` -> ``u`` (fixpoint); delete non-word-initial short vowels;
   drop a word-final schwa ``a``.
6. Nasal normalisation: ``ng`` -> ``n``, ``nk`` -> ``n``, ``m`` -> ``n``;
   anusvara/chandrabindu dropped.
"""

from __future__ import annotations

import re

from lexiforge.canon import canon

SKELETON_VERSION = "hingskel-v1.0"

_CH = "\x00"  # placeholder shielding "ch" from the step-2 c->k rule
_VV = "\x01"  # placeholder for the step-2 v<->w swap

_C_BEFORE_AOU = re.compile(r"c(?=[aou])")
_SOFT_C = re.compile(r"c(?=[eiy])")
_GEMINATE = re.compile(r"([b-df-hj-np-tv-z])\1+")

_ASPIRATES = (
    ("kh", "k"),
    ("gh", "g"),
    ("ch", "c"),
    ("jh", "j"),
    ("th", "t"),
    ("dh", "d"),
    ("ph", "p"),
    ("bh", "b"),
)

_SHORT_VOWELS = frozenset("aeiou")


def _step_roman_hindi(s: str) -> str:
    s = s.replace("ch", _CH)
    s = _C_BEFORE_AOU.sub("k", s)
    s = s.replace(_CH, "ch")
    s = s.replace("ph", "f")
    s = s.replace("v", _VV).replace("w", "v").replace(_VV, "w")
    s = s.replace("q", "k")
    s = s.replace("z", "j")
    s = s.replace("x", "ks")
    return s


def _step_aspiration(s: str) -> str:
    for src, dst in _ASPIRATES:
        s = s.replace(src, dst)
    return s


def _step_coronal(s: str) -> str:
    s = s.replace("sh", "s")
    s = _SOFT_C.sub("s", s)
    s = s.replace("c", "k")
    s = _GEMINATE.sub(r"\1", s)
    s = s.replace("d", "t")
    s = s.replace("y", "i")
    s = s.replace("w", "v")
    return s


def _compress_word(word: str) -> str:
    while True:
        folded = word.replace("aa", "a").replace("ee", "i").replace("oo", "u")
        if folded == word:
            break
        word = folded
    if not word:
        return word
    head, tail = word[0], word[1:]
    tail = "".join(ch for ch in tail if ch not in _SHORT_VOWELS)
    word = head + tail
    if len(word) > 1 and word.endswith("a"):
        word = word[:-1]  # final schwa
    return word


def _step_vowels(s: str) -> str:
    return " ".join(_compress_word(w) for w in s.split(" "))


def _step_nasal(s: str) -> str:
    s = s.replace("ng", "n").replace("nk", "n").replace("m", "n")
    s = s.replace("ं", "").replace("ँ", "")
    return s


def skeleton(text: str) -> str:
    """Return the HING-SKEL key for ``text``.

    Pure and deterministic: equal inputs give equal outputs, and the
    empty/whitespace input maps to ``""``.
    """
    s = canon(text)
    if not s:
        return ""
    s = _step_roman_hindi(s)
    s = _step_aspiration(s)
    s = _step_coronal(s)
    s = _step_vowels(s)
    s = _step_nasal(s)
    return " ".join(s.split())


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def skeleton_similarity(a: str, b: str) -> float:
    """Return ``1 - lev/max_len`` over skeleton keys.

    ``0.0`` when either skeleton is empty (including both empty), ``1.0``
    for identical non-empty skeletons. Always in ``[0.0, 1.0]``.
    """
    sa, sb = skeleton(a), skeleton(b)
    if not sa or not sb:
        return 0.0
    return 1.0 - _lev(sa, sb) / max(len(sa), len(sb))


def is_hard_negative_pair(a: str, b: str, pairs=None) -> bool:
    """Return True when ``a``/``b`` must not be merged phonetically.

    True when the two terms collide to the same skeleton while remaining
    canonically distinct (the phonetic veto), or when their
    canon-normalised forms appear as a registered entry in ``pairs``
    (order-insensitive). Identical terms return False. ``pairs`` may be
    any iterable of ``(x, y)`` string pairs or None.
    """
    ca, cb = canon(a), canon(b)
    if ca == cb:
        return False
    if skeleton(a) == skeleton(b):
        return True
    if pairs:
        for x, y in pairs:
            cx, cy = canon(x), canon(y)
            if (ca == cx and cb == cy) or (ca == cy and cb == cx):
                return True
    return False
