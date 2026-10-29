"""Tests for lexiforge.scripts.validate (design §4 step 3, checks S1-S10)."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from lexiforge.scripts import validate as V

REPO_ROOT = Path(__file__).resolve().parents[1]

REAL_TERMS = ["NEFT", "UPI", "KYC", "IFSC"]
FICT_TERMS = ["ArthSathi", "DhanSetu", "KhataKosh"]
GLOSSARY = REAL_TERMS + FICT_TERMS + [
    "NACH", "e-mandate", "policy", "premium", "claim",
    "forex", "currency", "mandate", "card-fraud",
]
MISMATCHED = ["policy", "premium", "claim", "forex", "currency"]
REAL_LEXICON = ["NEFT", "UPI", "KYC", "IFSC", "NACH", "e-mandate"]

T1 = ("AGT", "Namaste, thank you for calling customer care. "
           "How may I help you today with your account query?")
T2 = ("CUS", "I want to track my NEFT transfer linked to ArthSathi wallet. "
             "Please share the current status.")
T3 = ("AGT", "Sure. Please confirm the UPI reference number registered "
             "under DhanSetu so I can verify it.")
T4 = ("CUS", "My KYC document upload for KhataKosh failed twice. "
             "Please guide me on the next step.")
T5 = ("AGT", "I have noted the IFSC error flag. "
             "The team will call back shortly to close this request.")


def make_call(call_id="c01"):
    return {
        "call_id": call_id,
        "turns": [
            {"speaker": s, "text": t} for s, t in (T1, T2, T3, T4, T5)
        ],
        "metadata": {
            "call_id": call_id,
            "call_type": "upi",
            "channel": "phone",
            "language": "Hinglish",
            "speaker_pair": ["Asha", "Ravi"],
        },
        "expected_real_terms": list(REAL_TERMS),
        "expected_fictional_terms": list(FICT_TERMS),
        "mismatched_terms": [m for m in MISMATCHED],
        "oov_terms": [],
    }


def make_assignment(call_id="c01"):
    return {
        "call_id": call_id,
        "expected_real_terms": list(REAL_TERMS),
        "expected_fictional_terms": list(FICT_TERMS),
        "hard_negative_assigned": False,
        "hard_negative_pair": None,
        "oov_terms": [],
        "oov_assigned": False,
        "mismatched_domain": "insurance",
    }


def codes(violations):
    return {v.split(" ", 1)[0] for v in violations}


def check_script(call, assignment, mismatched=MISMATCHED):
    return V.validate_script(
        copy.deepcopy(call), copy.deepcopy(assignment),
        list(GLOSSARY), list(mismatched),
    )


def check_corpus(call, assignment, mismatched=MISMATCHED, cid="c01"):
    c = copy.deepcopy(call)
    a = copy.deepcopy(assignment)
    c.setdefault("mismatched_terms", list(mismatched))
    return V.validate_corpus([c], {cid: a}, list(GLOSSARY), list(REAL_LEXICON))


def test_valid_mini_call_passes():
    call, assignment = make_call(), make_assignment()
    assert check_script(call, assignment) == []
    assert check_corpus(call, assignment) == []


def test_s1_fires_on_wrong_order():
    call, assignment = make_call(), make_assignment()
    call["turns"][0]["speaker"], call["turns"][1]["speaker"] = "CUS", "AGT"
    vs = check_script(call, assignment)
    assert "S1" in codes(vs)
    assert check_corpus(call, assignment, cid="c01")


def test_s1_fires_on_wrong_count():
    call, assignment = make_call(), make_assignment()
    call["turns"] = call["turns"][:4]
    assert "S1" in codes(check_script(call, assignment))


def test_s2_fires_on_long_turn():
    call, assignment = make_call(), make_assignment()
    call["turns"][4]["text"] += " " + " ".join(["please"] * 50)
    vs = check_script(call, assignment)
    assert "S1" not in codes(vs)
    assert "S2" in codes(vs)


def test_s3_fires_on_missing_real_term():
    call, assignment = make_call(), make_assignment()
    call["turns"][1]["text"] = call["turns"][1]["text"].replace("NEFT", "fund")
    vs = check_script(call, assignment)
    assert "S3" in codes(vs)


def test_s3_fires_on_too_many_fictional():
    call, assignment = make_call(), make_assignment()
    call["turns"][4]["text"] += " Also check ArthSathi and DhanSetu status."
    assert "S3" in codes(check_script(call, assignment))


def test_s4_fires_on_term_in_turn_one():
    call, assignment = make_call(), make_assignment()
    call["turns"][0]["text"] += " My NEFT query is urgent."
    vs = check_script(call, assignment)
    assert "S4" in codes(vs)
    assert "S3" not in codes(vs)  # 5 real occurrences still in range


def test_s5_fires_on_mismatched_overlap():
    call, assignment = make_call(), make_assignment()
    vs = check_script(call, assignment, mismatched=MISMATCHED + ["NEFT"])
    assert "S5" in codes(vs)
    assert len(codes(vs)) == 1


def test_s6_fires_when_assigned_pair_absent():
    call, assignment = make_call(), make_assignment()
    assignment["hard_negative_assigned"] = True
    assignment["hard_negative_pair"] = ["NACH", "e-mandate"]
    vs = check_script(call, assignment)
    assert "S6" in codes(vs)
    assert check_corpus(call, assignment)


def test_s6_fires_when_unassigned_pair_present():
    call, assignment = make_call(), make_assignment()
    call["turns"][4]["text"] += " Choose NACH or e-mandate for autopay."
    assignment["hard_negative_pair"] = ["NACH", "e-mandate"]
    assert "S6" in codes(check_script(call, assignment))


def test_s7_fires_when_designated_oov_missing():
    call, assignment = make_call(), make_assignment()
    assignment["oov_assigned"] = True
    assignment["oov_terms"] = ["UPI lite"]
    call["oov_terms"] = ["UPI lite"]
    assert "S7" in codes(check_script(call, assignment))


def test_s7_fires_when_oov_in_glossary():
    call, assignment = make_call(), make_assignment()
    assignment["oov_assigned"] = True
    assignment["oov_terms"] = ["NEFT"]
    call["turns"][4]["text"] += " The NEFT lane stays up late."
    call["oov_terms"] = ["NEFT"]
    assert "S7" in codes(check_script(call, assignment))


def test_s8_fires_on_brand_name():
    call, assignment = make_call(), make_assignment()
    call["turns"][4]["text"] += " Paid via Paytm."
    vs = check_script(call, assignment)
    assert "S8" in codes(vs)
    assert "S9" not in codes(vs)  # Paytm is not a glossary term


def test_s9_fires_on_three_terms_in_turn():
    call, assignment = make_call(), make_assignment()
    call["turns"][1]["text"] += " The KYC helpline is busy."
    vs = check_script(call, assignment)
    assert "S9" in codes(vs)
    assert "S3" not in codes(vs)


def test_s9_fires_on_repeat_and_gloss():
    call, assignment = make_call(), make_assignment()
    call["turns"][2]["text"] += " UPI means instant rail."
    assert "S9" in codes(check_script(call, assignment))


def test_s10_fires_on_bad_metadata():
    call, assignment = make_call(), make_assignment()
    call["metadata"] = dict(call["metadata"])
    call["metadata"]["call_id"] = "c99"
    vs = check_script(call, assignment)
    assert "S10" in codes(vs)
    assert len(codes(vs)) == 1


def test_s10_fires_on_missing_key():
    call, assignment = make_call(), make_assignment()
    del call["metadata"]["channel"]
    assert "S10" in codes(check_script(call, assignment))


def test_corpus_valid_mini_passes():
    calls = [make_call(f"c0{i}") for i in (1, 2)]
    assigns = {f"c0{i}": make_assignment(f"c0{i}") for i in (1, 2)}
    for c in calls:
        c["mismatched_terms"] = list(MISMATCHED)
    assert V.validate_corpus(calls, assigns, GLOSSARY, REAL_LEXICON) == []


def _write_corpus_dir(root: Path, bad=False):
    (root).mkdir(parents=True, exist_ok=True)
    call = make_call("c01")
    assignment = make_assignment("c01")
    if bad:
        call["turns"] = call["turns"][:4]
    call["mismatched_terms"] = [m for m in MISMATCHED]
    (root / "c01.json").write_text(json.dumps(call), encoding="utf-8")
    (root / "assignment.json").write_text(
        json.dumps({"c01": assignment}), encoding="utf-8")
    (root / "glossary.json").write_text(
        json.dumps(GLOSSARY), encoding="utf-8")
    (root / "real_lexicon.json").write_text(
        json.dumps(REAL_LEXICON), encoding="utf-8")


def test_cli_exit_codes(tmp_path):
    good = tmp_path / "good"
    _write_corpus_dir(good)
    proc = subprocess.run(
        [sys.executable, "-m", "lexiforge.scripts.validate", str(good)],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr

    bad = tmp_path / "bad"
    _write_corpus_dir(bad, bad=True)
    proc = subprocess.run(
        [sys.executable, "-m", "lexiforge.scripts.validate", str(bad)],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "S1" in proc.stdout

    proc = subprocess.run(
        [sys.executable, "-m", "lexiforge.scripts.validate",
         str(tmp_path / "missing")],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert proc.returncode != 0
