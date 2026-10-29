"""Build the committed data artefacts from a seed.

Reproducible: running this twice with the same seed produces byte-identical
`data/glossary.json`, `data/core200.json` and `data/assignment.json`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lexiforge.glossary import validate as validate_mod
from lexiforge.glossary.assign import assign_terms
from lexiforge.glossary.core200 import build_core200, freeze
from lexiforge.glossary.generate import generate, glossary_hash, write_glossary

SEED = 1337
DATA = Path("data")

# Twenty calls across the banking call types the corpus targets.
CALL_TYPES = [
    "mandate_fail", "kyc_reverify", "upi_failed", "card_block", "collections",
    "loan_emi", "fd_rates", "netbanking_login", "fraud_dispute", "insurance",
    "chequebook", "forex_nri", "mandate_setup", "kyc_update", "upi_dispute",
    "card_limit", "collections_settlement", "loan_foreclosure", "branch_visit",
    "insurance_claim",
]


def main() -> None:
    DATA.mkdir(exist_ok=True)

    lexicon = json.loads((DATA / "lexicon.json").read_text(encoding="utf-8"))
    real_lexicon = [{"canonical": t["term"]} for t in lexicon["real_terms"]]
    brand_blocklist = [b.casefold() for b in lexicon["brand_blocklist"]]

    entries = generate(SEED, n_fictional=780, n_real=180, real_terms=[t["term"] for t in lexicon["real_terms"]])
    violations = validate_mod(entries, real_lexicon, brand_blocklist)
    if violations:
        raise SystemExit("glossary invalid:\n" + "\n".join(violations[:20]))

    write_glossary(DATA / "glossary.json", entries)
    glossary_sha = glossary_hash(DATA / "glossary.json")

    core = build_core200(entries, seed=SEED)
    freeze(DATA / "core200.json", core)

    assignment = assign_terms(entries, CALL_TYPES, SEED)
    (DATA / "assignment.json").write_text(
        json.dumps(assignment, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    calls = sorted(assignment)
    real = sum(len(v["real"]) for v in assignment.values())
    fict = sum(len(v["fictional"]) for v in assignment.values())
    oov = sum(1 for v in assignment.values() if v.get("oov"))
    pairs = sum(1 for v in assignment.values() if v.get("hard_negative_pair"))

    print(f"glossary      : {len(entries)} terms  sha={glossary_sha[:12]}")
    print(f"core-200      : {len(core['term_ids'])} ids")
    print(f"calls         : {len(calls)}")
    print(f"real terms    : {real} assignments ({real / max(len(calls), 1):.1f}/call)")
    print(f"fictional     : {fict} assignments ({fict / max(len(calls), 1):.1f}/call)")
    print(f"oov calls     : {oov}/6 expected")
    print(f"pairs         : {pairs}/10 expected")


if __name__ == "__main__":
    main()
