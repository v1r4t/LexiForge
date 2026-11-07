"""Cross-process determinism for mismatched/diluted context sampling.

Context construction is documented as "seeded per call" (docs/design.md), so the
same inputs must draw the same terms in a fresh interpreter regardless of
PYTHONHASHSEED. These tests run the builder in child processes with different
hash seeds and compare the resulting term sets.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_CHILD = """
import json

from lexiforge.canon import canon
from lexiforge.contexts.mismatch import build_dilution, build_mismatched

GLOSSARY = {
    "upi": ["UPI", "VPA", "IMPS", "RTGS", "BHIM"],
    # Set-valued domains: iteration order varies with PYTHONHASHSEED unless the
    # builder normalises it.
    "insurance": {
        "policy", "premium", "claim", "agent", "cover", "renewal",
        "rider", "deductible", "endowment", "annuity", "surrender", "nominee",
    },
    "forex": {
        "currency", "exchange", "remittance", "nostro", "swift", "hedge",
        "forward", "spot", "conversion", "corridor", "settlement", "margin",
    },
}
EXPECTED = ["NEFT", "KYC"]

payload = {
    "mismatched": sorted(
        canon(t) for t in build_mismatched(GLOSSARY, "upi", EXPECTED, seed=17, budget=4)
    ),
    "dilution": sorted(
        canon(t)
        for t in build_dilution(GLOSSARY, EXPECTED, call_type="upi", seed=17, budget=6)
    ),
}
print(json.dumps(payload, sort_keys=True))
"""


def _run_child(python_hash_seed: str) -> dict:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = python_hash_seed
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(ROOT), env.get("PYTHONPATH", "")) if p
    )
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_sampling_identical_across_python_hash_seeds():
    payload_0 = _run_child("0")
    payload_1 = _run_child("1")

    # Guard against a trivially passing comparison on empty output.
    assert len(payload_0["mismatched"]) == 4
    assert len(payload_0["dilution"]) == 6

    assert payload_0["mismatched"] == payload_1["mismatched"]
    assert payload_0["dilution"] == payload_1["dilution"]
