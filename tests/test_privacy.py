"""Tests for consent-preserving redaction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lexiforge.privacy import MASK_EMAIL, MASK_NUMBER, redact_object, redact_text


class TestRedactText:
    def test_plain_hinglish_sentence_is_untouched(self):
        text = "mera UPI fail ho gaya NEFT 5000 rupaye"
        assert redact_text(text) == (text, {})

    def test_glossary_terms_survive(self):
        for term in ("NEFT", "UPI", "KYC", "IFSC", "SBIN0001234"):
            redacted, counts = redact_text(f"{term} check karo")
            assert term in redacted
            assert counts == {}

    def test_phone_is_masked(self):
        redacted, counts = redact_text("mera number 9876543210 hai")
        assert "9876543210" not in redacted
        assert "[PHONE]" in redacted
        assert counts["[PHONE]"] == 1

    def test_phone_with_country_code(self):
        redacted, _ = redact_text("call +91 98765 43210")
        assert "98765" not in redacted

    def test_card_number_is_masked(self):
        redacted, counts = redact_text("card 4111 1111 1111 1111 block karo")
        assert "4111" not in redacted
        assert counts["[CARD]"] == 1

    def test_aadhaar_is_masked(self):
        redacted, counts = redact_text("aadhaar 1234 5678 9012 verify")
        assert "1234" not in redacted
        assert counts["[AADHAAR]"] == 1

    def test_account_number_is_masked(self):
        redacted, counts = redact_text("acct 123456789012345")
        assert "123456789012345" not in redacted
        assert counts[MASK_NUMBER] == 1

    def test_email_is_masked(self):
        redacted, counts = redact_text("rahul.sharma@example.com pe bhejo")
        assert "rahul" not in redacted
        assert counts[MASK_EMAIL] == 1

    def test_short_amounts_are_not_masked(self):
        for amount in ("500", "5000", "99999", "12345678"):
            redacted, counts = redact_text(f"amount {amount} rupaye")
            assert amount in redacted, amount
            assert counts == {}

    def test_devanagari_digits_are_caught(self):
        redacted, counts = redact_text("number ९८७६५४३२१० hai")
        assert "[PHONE]" in redacted
        assert counts

    def test_empty_and_none_safe(self):
        assert redact_text("") == ("", {})

    def test_repeated_values_keep_one_mask(self):
        text = "9876543210 aur 9123456780 dono"
        redacted, counts = redact_text(text)
        assert redacted.count("[PHONE]") == 2
        assert counts["[PHONE]"] == 2


class TestRedactObject:
    def test_recurses_through_json_shapes(self):
        payload = {
            "calls": [{"note": "phone 9876543210"}],
            "nested": {"deep": ["card 4111 1111 1111 1111"]},
            "count": 3,
            "flag": True,
        }
        redacted, counts = redact_object(payload)
        assert "9876543210" not in json.dumps(redacted)
        assert "4111" not in json.dumps(redacted)
        assert redacted["count"] == 3
        assert redacted["flag"] is True
        assert counts["[PHONE]"] == 1
        assert counts["[CARD]"] == 1


class TestExporterAppliesRedaction:
    def _project(self, tmp_path: Path) -> dict:
        glossary = tmp_path / "glossary.json"
        glossary.write_text(
            json.dumps([{"term_id": "R1", "canonical": "UPI", "scoring_aliases": ["UPI"]}]),
            encoding="utf-8",
        )
        refs = tmp_path / "refs"
        refs.mkdir()
        (refs / "c01_t01.json").write_text(
            json.dumps({"text": "mera UPI 9876543210 par fail ho gaya"}), encoding="utf-8"
        )
        transcripts = tmp_path / "transcripts" / "c01" / "baseline"
        transcripts.mkdir(parents=True)
        (transcripts / "c01_t01.json").write_text(
            json.dumps({"text": "mera UPI 9876543210 par fail ho gaya"}), encoding="utf-8"
        )
        return {"glossary": glossary, "refs": refs, "transcripts": tmp_path / "transcripts"}

    def test_export_masks_by_default(self, tmp_path: Path):
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from export_web_data import export

        project = self._project(tmp_path)
        out = tmp_path / "out"
        export(
            project["transcripts"],
            project["refs"],
            out,
            glossary_path=project["glossary"],
            assignment_path=tmp_path / "missing.json",
        )
        blob = (out / "transcripts.json").read_text(encoding="utf-8")
        assert "9876543210" not in blob
        assert "[PHONE]" in blob

        config = json.loads((out / "demo_config.json").read_text(encoding="utf-8"))
        assert config["redacted"] is True
        assert config["redaction_counts"]["[PHONE]"] >= 1

    def test_no_redact_keeps_raw_text(self, tmp_path: Path):
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from export_web_data import export

        project = self._project(tmp_path)
        out = tmp_path / "out-raw"
        export(
            project["transcripts"],
            project["refs"],
            out,
            glossary_path=project["glossary"],
            assignment_path=tmp_path / "missing.json",
            redact=False,
        )
        blob = (out / "transcripts.json").read_text(encoding="utf-8")
        assert "9876543210" in blob
        config = json.loads((out / "demo_config.json").read_text(encoding="utf-8"))
        assert config["redacted"] is False


@pytest.mark.parametrize("text", ["", " ", "मेरा UPI fail"])
def test_redaction_is_idempotent(text):
    once, _ = redact_text(text)
    twice, _ = redact_text(once)
    assert once == twice
