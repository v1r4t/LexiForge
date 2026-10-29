"""Tests for the synthetic glossary generator (design §4 step 1)."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from lexiforge.canon import canon
from lexiforge.glossary.generate import (
    CATEGORIES,
    NONCE_ROOTS,
    generate,
    glossary_hash,
    lev_distance,
    write_glossary,
)

SEED = 20261029
N_FICT, N_REAL = 20, 30


def _small(seed=SEED):
    return generate(seed, n_fictional=N_FICT, n_real=N_REAL)


class TestDeterminism(unittest.TestCase):
    def test_same_seed_byte_identical(self):
        first, second = _small(), _small()
        self.assertEqual(first, second)
        dump = lambda e: json.dumps(e, ensure_ascii=False, indent=2, sort_keys=True)
        self.assertEqual(dump(first), dump(second))

    def test_write_glossary_stable_bytes(self):
        entries = _small()
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "a.json", Path(tmp) / "b.json"
            write_glossary(first, entries)
            write_glossary(second, list(reversed(entries)))
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(glossary_hash(first), glossary_hash(second))

    def test_write_glossary_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.json"
            write_glossary(path, _small())
            text = path.read_text(encoding="utf-8")
            self.assertIn('\n  {', text)  # 2-space indent at entry level
            self.assertIn('\n    "canonical"', text)  # 4-space indent at key level
            self.assertNotIn("\\u", text)  # ensure_ascii=False: raw Devanagari


class TestSchema(unittest.TestCase):
    def test_counts_and_origins(self):
        entries = _small()
        self.assertEqual(len(entries), N_FICT + N_REAL)
        origins = [e["origin"] for e in entries]
        self.assertEqual(origins.count("fictional"), N_FICT)
        self.assertEqual(origins.count("real"), N_REAL)

    def test_entry_schema(self):
        for entry in _small():
            self.assertEqual(set(entry), {
                "term_id", "canonical", "script_variants", "spoken_forms",
                "scoring_aliases", "category", "origin", "freq_band", "provenance",
            })
            self.assertEqual(set(entry["script_variants"]), {"deva", "latn"})
            self.assertEqual(set(entry["provenance"]), {"source", "author"})
            self.assertTrue(entry["provenance"]["source"])
            self.assertTrue(entry["provenance"]["author"])
            self.assertIn(entry["freq_band"], ("head", "mid", "tail"))

    def test_every_entry_categorised(self):
        valid = set(CATEGORIES)
        self.assertEqual(len(valid), 12)
        for entry in _small():
            self.assertIsInstance(entry["category"], str)
            self.assertTrue(entry["category"])
            self.assertIn(entry["category"], valid)


class TestNoPairwiseCollisions(unittest.TestCase):
    def test_canonicals_unique_and_matcher_separate(self):
        entries = _small()
        lows = [e["canonical"].casefold() for e in entries]
        self.assertEqual(len(set(lows)), len(lows))
        keys = [canon(e["canonical"]) for e in entries]
        self.assertEqual(len(set(keys)), len(keys))  # frozen matcher keeps all apart

    def test_fictional_pairs_distance_at_least_3(self):
        entries = _small()
        fictional = [e for e in entries if e["origin"] == "fictional"]
        surfaces = [(e["canonical"].casefold(), e["term_id"]) for e in fictional]
        for aliases_of in fictional:
            for alias in aliases_of["scoring_aliases"]:
                surfaces.append((alias.casefold(), aliases_of["term_id"] + ":alias"))
        for i in range(len(surfaces)):
            for j in range(i + 1, len(surfaces)):
                (a, ia), (b, ib) = surfaces[i], surfaces[j]
                if ia.split(":")[0] == ib.split(":")[0]:
                    continue  # an entry's own alias sits 1 edit away by construction
                self.assertGreaterEqual(
                    lev_distance(a, b), 3, msg=f"{ia!r} vs {ib!r}")

    def test_fictional_clear_of_every_real(self):
        entries = _small()
        fictional = [e for e in entries if e["origin"] == "fictional"]
        reals = [e["canonical"].casefold() for e in entries if e["origin"] == "real"]
        for entry in fictional:
            for surface in [entry["canonical"], *entry["scoring_aliases"]]:
                for real in reals:
                    self.assertGreaterEqual(
                        lev_distance(surface.casefold(), real), 3,
                        msg=f"{surface!r} vs real {real!r}")


class TestFictionalRules(unittest.TestCase):
    def test_fictional_carry_nonce_root(self):
        for entry in _small():
            if entry["origin"] != "fictional":
                continue
            low = entry["canonical"].lower()
            self.assertTrue(any(root in low for root in NONCE_ROOTS),
                            msg=f"{entry['canonical']!r} carries no nonce root")

    def test_fictional_shape(self):
        for entry in _small():
            if entry["origin"] != "fictional":
                continue
            name = entry["canonical"]
            self.assertRegex(name, r"^[A-Z][a-zA-Z]*$")  # CamelCase, single token
            self.assertTrue(any(ch.isupper() for ch in name[1:]))
            syllables = len(re.findall(r"[aeiou]+", name.lower()))
            self.assertGreaterEqual(syllables, 2)
            self.assertLessEqual(syllables, 4)
            for part in re.split(r"(?<=[a-z])(?=[A-Z])", name):
                self.assertIsNone(re.match(r"^[^aeiouAEIOU]{3}", part),
                                  msg=f"triple-consonant onset in {name!r}")

    def test_aliases_only_by_spacing_case_rule(self):
        for entry in _small():
            bare = re.sub(r"[\s\-]", "", entry["canonical"]).casefold()
            for alias in entry["scoring_aliases"]:
                self.assertEqual(re.sub(r"[\s\-]", "", alias).casefold(), bare)


if __name__ == "__main__":
    unittest.main()
