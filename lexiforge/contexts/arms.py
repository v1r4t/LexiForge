"""The five experiment arms (design §2).

The same audio, model and format are decoded once per arm; only the keyterm
list changes:

* ``baseline`` — no keyterms. Also produces the pass-1 transcript that feeds
  the adaptive selector.
* ``selected-200`` — the selector's natural set, padded deterministically from
  the full glossary so the arm carries exactly ``budget`` slots.
* ``mismatched-200`` — off-domain terms, zero canonical overlap with the
  expected set.
* ``hard-negative-200`` — terms phonetically/orthographically close to the
  expected set, zero exact canonical overlap with it.
* ``static-200`` — one fixed glossary list, identical for every call.

Every arm except ``baseline`` is asserted to exactly ``budget`` unique
canonical surfaces: a short list silently turns an equal-budget contrast into
a dose comparison. The selector underfills by design, so the selected arm pads
instead of shrinking.

T6 owns hard-negative generation. It is imported lazily inside the builder so
this module can be imported before T6 merges and tests can inject a fake.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Optional

from lexiforge.canon import canon
from lexiforge.contexts.build import MAX_KEYTERMS, build_config
from lexiforge.contexts.mismatch import build_mismatched
from lexiforge.optimizer.vocab import to_selector_glossary
from lexiforge.select.ranker import select

ARMS = (
    "baseline",
    "selected-200",
    "mismatched-200",
    "hard-negative-200",
    "static-200",
)

HardNegativeBuilder = Callable[..., list[str]]

_ID_KEYS = ("term_id", "id", "termId")
_SURFACE_KEYS = ("canonical", "term", "name")
_ALIAS_KEYS = ("scoring_aliases", "aliases", "alias", "variants", "surfaces")

# Script ``call_type`` values are not glossary categories. Without this map
# ``build_mismatched`` sees a key that matches no category and treats every
# category as off-domain, including the expected terms' own domain.
_FLAT_CATEGORY = "__glossary__"

_CALL_TYPE_CATEGORIES = {
    "mandate": "mandates_autopay",
    "mandate_fail": "mandates_autopay",
    "kyc": "identity_kyc",
    "kyc_reverify": "identity_kyc",
    "kyc_update": "identity_kyc",
    "payment": "payments",
    "payments": "payments",
    "upi": "payments",
    "upi_dispute": "payments",
    "upi_failed": "payments",
    "card": "cards",
    "cards": "cards",
    "card_block": "cards",
    "card_limit": "cards",
    "collections": "collections_recovery",
    "collections_settlement": "collections_recovery",
    "loan": "loans_credit",
    "loans": "loans_credit",
    "loan_emi": "loans_credit",
    "loan_foreclosure": "loans_credit",
    "branch_visit": "statements_servicing",
    "chequebook": "statements_servicing",
    "netbanking_login": "statements_servicing",
    "statements": "statements_servicing",
    "fraud": "fraud_disputes",
    "fraud_dispute": "fraud_disputes",
    "insurance": "insurance",
    "insurance_claim": "insurance",
    "forex": "forex_trade",
    "forex_nri": "forex_trade",
    "transfer": "transfers",
    "transfers": "transfers",
    "deposits": "deposits_savings",
    "fd_rates": "deposits_savings",
}


@dataclass(frozen=True)
class _GlossaryIndex:
    """Normalised view of the committed glossary."""

    entries: list[dict]
    pool: list[str]
    id_to_surface: dict[str, str]
    canon_to_surface: dict[str, str]
    categories: dict[str, list[str]]


def _surface(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _assert_no_reference(value: Any, *, where: str) -> None:
    """Reject any ``reference`` key so ground truth cannot leak into an arm."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "reference":
                raise TypeError(f"{where} must not contain a 'reference' key")
            _assert_no_reference(item, where=where)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _assert_no_reference(item, where=where)


def _entry_id(entry: Mapping, idx: int) -> str:
    for key in _ID_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError(f"glossary entry {idx} has no term_id/id key")


def _entry_surface(entry: Mapping, tid: str) -> str:
    for key in _SURFACE_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return _surface(value)
    return tid


def _string_items(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (set, frozenset)):
        return [item for item in sorted(value, key=str) if isinstance(item, str)]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str)]
    return []


def _entry_forms(entry: Mapping, tid: str) -> list[str]:
    forms: list[str] = []
    for key in _ALIAS_KEYS:
        forms.extend(_string_items(entry.get(key)))
    for key in _SURFACE_KEYS:
        forms.extend(_string_items(entry.get(key)))
    variants = entry.get("script_variants")
    if isinstance(variants, Mapping):
        forms.extend(
            item for item in variants.values() if isinstance(item, str)
        )
    forms.extend(_string_items(entry.get("spoken_forms")))
    forms.append(tid)
    return forms


def _unique_sorted(surfaces: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for surface in surfaces:
        key = canon(surface)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(surface)
    return sorted(out, key=lambda s: (canon(s), s))


def _index_glossary(glossary: Iterable[dict]) -> _GlossaryIndex:
    if isinstance(glossary, (str, bytes)):
        raise TypeError("glossary must be an iterable of dicts")
    entries = list(glossary)
    surfaces: list[str] = []
    id_to_surface: dict[str, str] = {}
    canon_to_surface: dict[str, str] = {}
    categories: dict[str, list[str]] = {}

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise TypeError(f"glossary entry {idx} must be a dict")
        tid = _entry_id(entry, idx)
        surface = _entry_surface(entry, tid)
        id_to_surface.setdefault(tid, surface)

        key = canon(surface)
        if key and key not in canon_to_surface:
            canon_to_surface[key] = surface
        surfaces.append(surface)

        for form in _entry_forms(entry, tid):
            form_key = canon(form)
            if form_key and form_key not in canon_to_surface:
                canon_to_surface[form_key] = surface

        category = entry.get("category")
        if isinstance(category, str) and category.strip():
            categories.setdefault(category.strip(), []).append(surface)

    return _GlossaryIndex(
        entries=entries,
        pool=_unique_sorted(surfaces),
        id_to_surface=id_to_surface,
        canon_to_surface=canon_to_surface,
        categories={
            name: _unique_sorted(terms) for name, terms in categories.items()
        },
    )


def _resolve_terms(
    values: Iterable[str], index: _GlossaryIndex, *, name: str
) -> list[str]:
    """Map IDs/aliases to canonical surfaces, preserving first-seen order."""
    if isinstance(values, str):
        raise TypeError(f"{name} must be an iterable of str, not str")
    if isinstance(values, (set, frozenset)):
        values = sorted(values, key=str)

    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise TypeError(f"{name} entries must be str")
        text = _surface(value)
        if not text:
            continue
        resolved = index.id_to_surface.get(text)
        if resolved is None:
            resolved = index.canon_to_surface.get(canon(text), text)
        key = canon(resolved)
        if key and key not in seen:
            seen.add(key)
            out.append(resolved)
    return out


def _pad(
    items: Iterable[str],
    budget: int,
    pool: Iterable[str],
    *,
    exclude: Iterable[str] = (),
) -> list[str]:
    """Fill to exactly ``budget`` unique terms from a deterministic pool."""
    if budget == 0:
        return []
    blocked = {canon(term) for term in exclude if canon(term)}
    chosen: list[str] = []
    seen: set[str] = set(blocked)

    def take(term: str) -> None:
        key = canon(term)
        if not key or key in seen:
            return
        seen.add(key)
        chosen.append(term)

    for term in items:
        if len(chosen) >= budget:
            break
        take(term)
    if len(chosen) < budget:
        for term in pool:
            if len(chosen) >= budget:
                break
            take(term)
    if len(chosen) != budget:
        raise ValueError(
            f"cannot build an exact {budget}-term arm: only "
            f"{len(chosen)} unique terms available"
        )
    return chosen


def _natural_selected(
    hypothesis: Any, index: _GlossaryIndex, call_type: str, budget: int
) -> list[str]:
    selector_glossary = to_selector_glossary(index.entries)
    ids = select(hypothesis, selector_glossary, call_type, budget=budget)
    return [index.id_to_surface.get(tid, tid) for tid in ids]


def _category_mapping(
    index: _GlossaryIndex, by_category: Optional[Mapping[str, Iterable[str]]]
) -> dict[str, list[str]]:
    if by_category is None:
        mapping = {name: list(terms) for name, terms in index.categories.items()}
    else:
        if not isinstance(by_category, Mapping):
            raise TypeError("by_category must be a mapping of category -> terms")
        mapping = {}
        for name, terms in by_category.items():
            if not isinstance(name, str):
                raise TypeError("by_category keys must be strings")
            mapping[name.strip()] = _resolve_terms(
                terms, index, name=f"by_category[{name!r}]"
            )

    cleaned = {
        name: _unique_sorted(terms) for name, terms in mapping.items() if terms
    }
    if not cleaned:
        # build_mismatched expects a domain-keyed mapping; a flat scan can
        # raise on ambiguous inputs, so always hand it one explicit domain.
        cleaned = {_FLAT_CATEGORY: list(index.pool)}
    return cleaned


def _normalise_call_type(value: str) -> str:
    return "_".join(value.strip().lower().replace("-", " ").split())


def _call_type_category(
    call_type: str, categories: Mapping[str, list[str]]
) -> Optional[str]:
    """Resolve a script call type to the glossary category it belongs to."""
    key = _normalise_call_type(call_type)
    for name in categories:
        if _normalise_call_type(name) == key:
            return name
    mapped = _CALL_TYPE_CATEGORIES.get(key)
    if mapped in categories:
        return mapped
    return None


def _expected_categories(
    mapping: Mapping[str, list[str]], expected: Iterable[str]
) -> set[str]:
    """Every category that contains at least one expected term."""
    expected_keys = {canon(term) for term in expected if canon(term)}
    return {
        name
        for name, terms in mapping.items()
        if any(canon(term) in expected_keys for term in terms)
    }


def _limit_to_budget(
    mapping: Mapping[str, list[str]], budget: int
) -> dict[str, list[str]]:
    """Keep only enough categories to fill ``budget`` unique terms."""
    if budget <= 0:
        return {}
    chosen: dict[str, list[str]] = {}
    seen: set[str] = set()
    for name in sorted(mapping):
        chosen[name] = mapping[name]
        seen.update(canon(term) for term in mapping[name] if canon(term))
        if len(seen) >= budget:
            break
    return chosen


def _off_domain_mapping(
    mapping: Mapping[str, list[str]],
    call_type: str,
    expected: Iterable[str],
    *,
    budget: int,
) -> dict[str, list[str]]:
    """Drop the call's own category and every category holding expected terms.

    When the call type has no mapping and the expected terms belong to no
    category, there is no domain signal at all; take only as many categories as
    the budget needs instead of treating the whole glossary as off-domain.
    """
    own = _call_type_category(call_type, mapping)
    expected_cats = _expected_categories(mapping, expected)
    if set(mapping) == {_FLAT_CATEGORY}:
        # A glossary without categories has no domain structure to exclude;
        # expected surfaces are still removed canonically when drawing.
        expected_cats = set()
    excluded = expected_cats | ({own} if own is not None else set())
    allowed = {
        name: terms for name, terms in mapping.items() if name not in excluded
    }
    if not allowed:
        # The live baseline transcript can mention terms from every category,
        # so a strictly off-domain arm may be impossible. Fall back to the
        # full glossary (minus the call's own category when known) and rely on
        # canonical term-level exclusion; the report records the weaker arm.
        allowed = {name: terms for name, terms in mapping.items() if name != own}
    if not allowed:
        allowed = dict(mapping)
    if not allowed:
        raise ValueError(
            "cannot build a mismatched arm: the glossary has no usable terms"
        )
    if own is None and not expected_cats:
        allowed = _limit_to_budget(allowed, budget)
    return allowed


def _build_mismatched(
    index: _GlossaryIndex,
    call_type: str,
    expected: list[str],
    *,
    seed: int,
    budget: int,
    by_category: Optional[Mapping[str, Iterable[str]]],
) -> list[str]:
    if budget == 0:
        return []
    mapping = _category_mapping(index, by_category)
    off_domain = _off_domain_mapping(mapping, call_type, expected, budget=budget)
    expected_keys = {canon(term) for term in expected}
    off_domain_keys = {
        canon(term)
        for terms in off_domain.values()
        for term in terms
        if canon(term) and canon(term) not in expected_keys
    }
    if len(off_domain_keys) < budget:
        # No strictly off-domain pool can fill the arm. Keep exact budget and
        # zero overlap by drawing from the full glossary; the report records
        # the weaker off-domain guarantee.
        off_domain = dict(mapping)
        own = None
    else:
        own = _call_type_category(call_type, off_domain)
    # ``own`` may have been removed; this sentinel never suppresses a category.
    draw_key = own if own is not None else "__off_domain__"
    drawn = build_mismatched(
        off_domain, draw_key, expected, seed=seed, budget=budget
    )
    pool = _unique_sorted(index.pool)
    return _pad(
        drawn,
        budget,
        pool,
        exclude=expected_keys,
    )


def _build_hard_negative(
    glossary: list[dict],
    index: _GlossaryIndex,
    expected: list[str],
    *,
    seed: int,
    budget: int,
    builder: Optional[HardNegativeBuilder],
) -> list[str]:
    if builder is None:
        # T6 owns this module and merges before T5: lazy import keeps this
        # module importable on its own and lets tests inject a fake builder.
        from lexiforge.contexts.hard_negative import build_hard_negative

        builder = build_hard_negative

    terms = builder(glossary, expected, budget=budget, seed=seed)
    if not isinstance(terms, (list, tuple)):
        raise TypeError("hard_negative_builder must return a list of strings")
    resolved = _resolve_terms(
        terms, index, name="hard_negative_builder output"
    )
    return _pad(
        resolved,
        budget,
        index.pool,
        exclude={canon(term) for term in expected},
    )


def _build_static(
    index: _GlossaryIndex,
    static_terms: Optional[Iterable[str]],
    *,
    budget: int,
) -> list[str]:
    if static_terms is None:
        # One fixed list, independent of the hypothesis and call type. The
        # canonical sort makes it stable across PYTHONHASHSEED and glossary
        # permutations.
        chosen = list(index.pool)
    else:
        chosen = _resolve_terms(static_terms, index, name="static_terms")
    return _pad(chosen, budget, index.pool)


def _validate_budget(budget: int) -> None:
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise TypeError(f"budget must be an int, got {type(budget).__name__}")
    if budget < 0 or budget > MAX_KEYTERMS:
        raise ValueError(
            f"budget must be between 0 and {MAX_KEYTERMS}, got {budget}"
        )


def build_arms(
    hypothesis: str,
    glossary: list[dict],
    call_type: str,
    *,
    budget: int = 200,
    seed: int = 0,
    expected_terms: Optional[Iterable[str]] = None,
    static_terms: Optional[Iterable[str]] = None,
    by_category: Optional[Mapping[str, Iterable[str]]] = None,
    hard_negative_builder: Optional[HardNegativeBuilder] = None,
    pad_selected: bool = True,
) -> dict[str, list[str]]:
    """Build the five keyterm lists for one call.

    ``expected_terms`` may be glossary IDs or canonical/alias surfaces; the
    controls receive canonical surfaces. It defaults to the selected arm's
    natural (pre-pad) set, which keeps the builder usable without ground truth.
    ``by_category`` overrides the adapter that groups glossary entries by their
    ``category`` field for the mismatched arm. Set ``pad_selected=False`` to
    keep the selector's natural list; the wrong-list controls stay exact-budget.
    """
    _assert_no_reference(hypothesis, where="hypothesis")
    _assert_no_reference(glossary, where="glossary")
    _assert_no_reference(static_terms, where="static_terms")
    _assert_no_reference(by_category, where="by_category")
    _validate_budget(budget)
    if not isinstance(call_type, str):
        raise TypeError(f"call_type must be a str, got {type(call_type).__name__}")

    index = _index_glossary(glossary)
    if expected_terms is None:
        expected = _natural_selected(hypothesis, index, call_type, budget)
    else:
        expected = _resolve_terms(expected_terms, index, name="expected_terms")
        expected.sort(key=lambda term: (canon(term), term))

    natural = _natural_selected(hypothesis, index, call_type, budget)
    selected = _pad(natural, budget, index.pool) if pad_selected else natural

    return {
        "baseline": [],
        "selected-200": selected,
        "mismatched-200": _build_mismatched(
            index,
            call_type,
            expected,
            seed=seed,
            budget=budget,
            by_category=by_category,
        ),
        "hard-negative-200": _build_hard_negative(
            index.entries,
            index,
            expected,
            seed=seed,
            budget=budget,
            builder=hard_negative_builder,
        ),
        "static-200": _build_static(index, static_terms, budget=budget),
    }


def build_arm_configs(
    hypothesis: str,
    glossary: list[dict],
    call_type: str,
    *,
    budget: int = 200,
    seed: int = 0,
    expected_terms: Optional[Iterable[str]] = None,
    static_terms: Optional[Iterable[str]] = None,
    by_category: Optional[Mapping[str, Iterable[str]]] = None,
    hard_negative_builder: Optional[HardNegativeBuilder] = None,
    pad_selected: bool = True,
) -> dict[str, dict]:
    """Build one validated context config per arm.

    ``baseline`` carries no ``keyterms`` field at all; an empty array would be
    a different request than "no keyterms".
    """
    arms = build_arms(
        hypothesis,
        glossary,
        call_type,
        budget=budget,
        seed=seed,
        expected_terms=expected_terms,
        static_terms=static_terms,
        by_category=by_category,
        hard_negative_builder=hard_negative_builder,
        pad_selected=pad_selected,
    )
    configs: dict[str, dict] = {}
    for arm in ARMS:
        if arm == "baseline":
            configs[arm] = build_config()
        else:
            configs[arm] = build_config(keyterms=arms[arm])
    return configs
