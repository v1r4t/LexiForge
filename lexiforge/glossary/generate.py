"""Synthetic glossary generator (design §4, pipeline step 1).

Builds the 2000-term glossary: ~90% real / ~10% fictional
(``docs/notes/fictional-terms-and-controls.md`` §5).

Fictional names: a nonce root from ``NONCE_ROOTS`` plus a Hindi/English
second element, CamelCase, 2-4 syllables, no triple-consonant onset.
Every fictional canonical (and each of its rule aliases) is Levenshtein
>= 3 from every other fictional surface and from every real term in
``data/lexicon.json`` (or the bundled real list when that file is absent).

Aliases exist ONLY by spacing/case rule (``VeloSathi`` -> ``Velo Sathi``);
each alias is covered by its entry's ``provenance`` (rule-generated, never
ASR-derived). Real-namespace terms are taken as given: short banking
acronyms (UPI/EMI/...) are inherently closer than 3 apart, so the >= 3
rule is enforced only on pairs involving at least one fictional term.

Deterministic: one ``random.Random(seed)`` stream, insertion-ordered
containers, entries sorted by ``term_id``. Same seed -> byte-identical
``write_glossary`` output.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from pathlib import Path

GENERATOR_VERSION = "glossary-gen-v1"

NONCE_ROOTS = ("velo", "zep", "tav", "nir", "ruv", "mor", "jiv", "khed")

SECOND_ELEMENTS = (
    "Sathi", "Dhan", "Nidhi", "Setu", "Udaan", "Khata", "Sewa", "Rupya",
    "Arth", "Kosh", "Mitra", "Kendra", "Bandhu", "Pay", "Saral", "Sugam",
    "Nivesh", "Bachat", "Hisaab", "Tijori", "Vyaj", "Karza", "Mudra",
    "Lekha", "Jama", "Sahay", "Rin", "Byaj", "Vyapaar", "Naya", "Sona",
    "Paisa", "Daam", "Laabh", "Gullak", "Bima", "Kist", "Lenden",
    "Kharcha", "Munafa", "Rozgar", "Naukri", "Vetan", "Bhatta", "Bharosa",
    "Vishwas", "Dhandha", "Sahukar", "Aamdani", "Suraksha", "Sahayta",
    "Heera", "Chandi", "Raseed", "Bahi", "Rokad", "Udhaar", "Dukaan",
    "Grahak", "Bazaar",
)

CATEGORIES = (
    "payments",
    "transfers",
    "identity_kyc",
    "loans_credit",
    "deposits_savings",
    "cards",
    "mandates_autopay",
    "insurance",
    "forex_trade",
    "collections_recovery",
    "fraud_disputes",
    "statements_servicing",
)

FREQ_BANDS = ("head", "mid", "tail")

BUNDLED_REAL_TERMS = (
    "NEFT", "UPI", "KYC", "IFSC", "NACH", "e-mandate", "UPI ID", "VPA",
    "MICR", "BBPS", "Bharat BillPay", "IMPS", "EMI", "CIBIL",
    "credit score", "Aadhaar", "PAN", "OTP", "PIN", "CVV", "debit card",
    "credit card", "savings account", "current account", "fixed deposit",
    "recurring deposit", "interest rate", "home loan", "personal loan",
    "overdraft", "cheque", "demand draft", "netbanking", "mobile banking",
    "wallet", "cashback", "refund", "statement", "balance", "transaction",
    "beneficiary", "nominee", "TDS", "GST", "BHIM", "PhonePe", "Paytm",
    "Razorpay", "Cashfree", "BillDesk", "Mobikwik", "Freecharge",
    "Jupiter", "Slice", "Niyo", "minimum balance", "account number",
    "branch code", "passbook", "equated monthly instalment",
    "know your customer", "KYC documents", "rate of interest",
    "loan account", "credit limit",
)

REAL_MODIFIERS = (
    "Plus", "Prime", "Max", "Lite", "Pro", "Edge", "Flex", "Secure",
    "Instant", "Smart", "Super", "Ultra", "Direct", "Active", "Rapid",
    "Swift", "Easy", "Power", "Shield", "Trust", "Care", "Connect",
    "Click", "Serve", "Assured", "Classic", "Select", "Elite", "Value",
    "Priority", "Advantage", "Reserve",
)

_LEXICON_CANDIDATES = ("data/lexicon.json",)

try:  # rapidfuzz is a declared dependency; C implementation keeps 2000-term builds fast.
    from rapidfuzz.distance import Levenshtein as _RFL

    def lev_distance(a: str, b: str) -> int:
        """Levenshtein distance on already-normalised (lowercased) strings."""
        return _RFL.distance(a, b)

except ImportError:  # pragma: no cover - fallback only.

    def lev_distance(a: str, b: str) -> int:
        if a == b:
            return 0
        la, lb = len(a), len(b)
        if abs(la - lb) >= 3 and min(la, lb) == 0:
            return max(la, lb)
        prev = list(range(lb + 1))
        for i in range(1, la + 1):
            cur = [i] + [0] * lb
            ca = a[i - 1]
            for j in range(1, lb + 1):
                cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != b[j - 1]))
            prev = cur
        return prev[lb]


_VOWEL_RUN = re.compile(r"[aeiou]+")
_TRIPLE_ONSET = re.compile(r"^[^aeiouAEIOU]{3}")
_CAMEL_SPLIT = re.compile(r"(?<=[a-z])(?=[A-Z])")
_WS_HYPHEN = re.compile(r"[\s\-]+")


def _count_syllables(canonical: str) -> int:
    letters = re.sub(r"[^a-z]", "", canonical.lower())
    return max(1, len(_VOWEL_RUN.findall(letters)))


def _has_triple_onset(canonical: str) -> bool:
    for token in _WS_HYPHEN.split(canonical):
        for part in _CAMEL_SPLIT.sub(" ", token).split(" "):
            if part and _TRIPLE_ONSET.match(part):
                return True
    return False


def _rule_aliases(canonical: str) -> list[str]:
    """Aliases by spacing/case rule only: no other derivation is allowed."""
    aliases: list[str] = []
    spaced = _CAMEL_SPLIT.sub(" ", canonical)
    if spaced != canonical:
        aliases.append(spaced)
    dehyphen = canonical.replace("-", " ").replace("  ", " ")
    if dehyphen != canonical and dehyphen not in aliases:
        aliases.append(dehyphen)
    return aliases


_LATN_TO_DEVA = {
    "a": "अ", "b": "ब", "c": "क", "d": "द", "e": "ए", "f": "फ",
    "g": "ग", "h": "ह", "i": "इ", "j": "ज", "k": "क", "l": "ल",
    "m": "म", "n": "न", "o": "ओ", "p": "प", "q": "क", "r": "र",
    "s": "स", "t": "त", "u": "उ", "v": "व", "w": "व", "x": "क्स",
    "y": "य", "z": "ज़",
}


def _has_devanagari(text: str) -> bool:
    return any("\u0900" <= ch <= "\u097f" for ch in text)


def _transliterate_to_deva(text: str) -> str:
    return "".join(_LATN_TO_DEVA.get(ch.lower(), ch) for ch in text)


def _load_real_source() -> tuple[list[str], str]:
    """Return (canonical real terms, provenance source label)."""
    here = Path(__file__).resolve()
    search = [here.parents[2] / "data" / "lexicon.json", Path.cwd() / "data" / "lexicon.json"]
    for candidate in _LEXICON_CANDIDATES:
        search.append(Path.cwd() / candidate)
    for path in search:
        try:
            if not path.is_file():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(raw, dict):
            for key in ("terms", "lexicon", "entries", "glossary"):
                if isinstance(raw.get(key), list):
                    raw = raw[key]
                    break
            else:
                continue
        if not isinstance(raw, list):
            continue
        terms: list[str] = []
        for item in raw:
            if isinstance(item, str):
                name = item
            elif isinstance(item, dict):
                name = item.get("canonical", item.get("term", item.get("name", item.get("text", ""))))
            else:
                continue
            name = unicodedata.normalize("NFC", str(name)).strip()
            if name:
                terms.append(name)
        if terms:
            return terms, "data/lexicon.json"
    return list(BUNDLED_REAL_TERMS), "bundled-real-list:v1"


def _make_entry(term_id: str, canonical: str, category: str, origin: str,
                freq_band: str, provenance: dict) -> dict:
    latn = unicodedata.normalize("NFC", canonical)
    deva = latn if _has_devanagari(latn) else _transliterate_to_deva(latn)
    return {
        "term_id": term_id,
        "canonical": latn,
        "script_variants": {"deva": deva, "latn": latn},
        "spoken_forms": [],
        "scoring_aliases": _rule_aliases(latn),
        "category": category,
        "origin": origin,
        "freq_band": freq_band,
        "provenance": provenance,
    }


def _surfaces(entry: dict) -> list[str]:
    return [entry["canonical"], *entry["scoring_aliases"]]


def generate(seed, n_fictional: int = 200, n_real: int = 1800) -> list[dict]:
    """Build the synthetic glossary deterministically from ``seed``."""
    rng = random.Random(seed)
    author = f"seed:{seed}"

    real_source, real_label = _load_real_source()
    seen: set[str] = set()
    ordered_real: list[str] = []
    for name in real_source:
        key = unicodedata.normalize("NFC", name).strip()
        if key and key.casefold() not in seen:
            seen.add(key.casefold())
            ordered_real.append(key)
    forbidden = [name.casefold() for name in ordered_real]

    fictional: list[dict] = []
    fict_surfaces: list[str] = []  # lowercased canonicals + aliases of accepted fictionals
    roots = [r.capitalize() for r in NONCE_ROOTS]
    pool = [f"{root}{second}" for root in roots for second in SECOND_ELEMENTS]
    rng.shuffle(pool)
    for canonical in pool:
        if len(fictional) >= n_fictional:
            break
        low = canonical.lower()
        if low in seen:
            continue
        if not 2 <= _count_syllables(canonical) <= 4:
            continue
        if _has_triple_onset(canonical):
            continue
        if any(lev_distance(low, other) < 3 for other in forbidden):
            continue
        if any(lev_distance(low, other) < 3 for other in fict_surfaces):
            continue
        aliases = _rule_aliases(canonical)
        if any(lev_distance(a.lower(), other) < 3 for a in aliases for other in fict_surfaces + forbidden):
            continue
        seen.add(low)
        fict_surfaces.append(low)
        fict_surfaces.extend(a.lower() for a in aliases)
        fictional.append(_make_entry(
            term_id=f"F{len(fictional) + 1:04d}",
            canonical=canonical,
            category=rng.choice(CATEGORIES),
            origin="fictional",
            freq_band=rng.choice(FREQ_BANDS),
            provenance={"source": f"nonce-root-generator:{GENERATOR_VERSION}", "author": author},
        ))
    if len(fictional) < n_fictional:
        raise ValueError(
            f"could only build {len(fictional)}/{n_fictional} fictional terms "
            "at Levenshtein >= 3; extend SECOND_ELEMENTS"
        )

    fict_canonicals = [e["canonical"].casefold() for e in fictional]

    real_names: list[str] = []
    if len(ordered_real) >= n_real:
        shuffled = ordered_real[:]
        rng.shuffle(shuffled)
        real_names = shuffled[:n_real]
    else:
        real_names = ordered_real[:]
        have = {n.casefold() for n in real_names}
        expansion_pool = [f"{base} {mod}" for base in ordered_real for mod in REAL_MODIFIERS]
        rng.shuffle(expansion_pool)
        for candidate in expansion_pool:
            if len(real_names) >= n_real:
                break
            name = unicodedata.normalize("NFC", candidate).strip()
            low = name.casefold()
            if low in have or low in seen:
                continue
            # Real namespace is taken as given (short acronyms are inherently
            # close); expansions must still keep clear of every fictional term.
            if any(lev_distance(low, f) < 3 for f in fict_canonicals):
                continue
            if any(lev_distance(low, a) < 3 for a in fict_surfaces):
                continue
            have.add(low)
            seen.add(low)
            real_names.append(name)
        if len(real_names) < n_real:
            raise ValueError(
                f"could only build {len(real_names)}/{n_real} real terms; "
                "extend BUNDLED_REAL_TERMS or REAL_MODIFIERS"
            )

    real: list[dict] = []
    for i, name in enumerate(real_names, start=1):
        real.append(_make_entry(
            term_id=f"R{i:04d}",
            canonical=name,
            category=rng.choice(CATEGORIES),
            origin="real",
            freq_band=rng.choice(FREQ_BANDS),
            provenance={"source": real_label, "author": author},
        ))

    entries = fictional + real
    entries.sort(key=lambda e: e["term_id"])
    return entries


def write_glossary(path, entries: list[dict]) -> str:
    """Write entries as stable sorted JSON (UTF-8, 2-space indent)."""
    out = Path(path)
    if out.parent != Path(".") and str(out.parent):
        out.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(entries, key=lambda e: e["term_id"])
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(ordered, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return str(out)


def glossary_hash(path) -> str:
    """SHA-256 hex of the glossary file bytes (replication manifest §6)."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
