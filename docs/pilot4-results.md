# Pilot 4 — six-arm synthetic result

**Scope:** Hinglish banking, synthetic TTS audio, 4 calls (c00–c03), 5 turns each,
`format=transliterate`, `language_code=hi-IN,en-IN`, budget 200.
**Internal harness validation — not customer evidence.**

## Arms

| Arm | Real recall | Fictional recall | Insertions / utterance | WER |
|---|---|---|---|---|
| baseline | 21/23 (91.3%) | 2/12 (16.7%) | 0.00 | 27.2% |
| selected-200 (brand-only, 8–9 terms) | 16/23 (69.6%) | 10/12 (83.3%) | 0.05 | 41.8% |
| mismatched-200 | 17/23 (73.9%) | 3/12 (25.0%) | 0.10 | 39.2% |
| hard-negative-200 | 18/23 (78.3%) | 2/12 (16.7%) | 0.20 | 41.3% |
| **oracle-200** | 19/23 (82.6%) | **12/12 (100.0%)** | 0.10 | 37.0% |
| static-head-200 | 17/23 (73.9%) | 6/12 (50.0%) | 0.00 | 34.1% |

## Pre-registered analysis

- **H1** — mismatched‑200 < baseline on real recall:
  mean **−17.5pp**, p = **0.062**, **not rejected**.
- **H2** — mismatched‑200 > baseline on insertions:
  mean **+0.10/utterance**, p = **0.503**, **not rejected**.
- **Holm** over H1/H2: neither rejected.
- **Positive control** — oracle‑200 − mismatched‑200 on real recall:
  **+9.17pp**, 95% CI [0.0, +18.3], direction passes, no p-value.
- **MDE** (observed, n=4): real recall ≈ 2.3pp, insertions ≈ 0.28/utterance.
- **Claim ladder:** mechanism only.

n=4 cannot reject at the pre-registered family: the smallest attainable
one-sided sign-flip p-value is 1/16 = 0.0625. The direction is consistent; the
sample is not.

## Findings

1. **Every keyterm list lowered real recall vs baseline**, including the oracle
   (82.6% vs 91.3%). The positive control still passes because oracle beats
   mismatched, so the pipeline responds to relevance.
2. **Brand/fictional recall behaves as intended**: oracle 100%, selected 83.3%,
   baseline 16.7%.
3. **Selected brand-only list is not free**: real recall −22.5pp vs baseline,
   insertions +0.05.
4. **The trade-off is the result**, not a selector bug. It may still be partly a
   transliteration/alias artefact; per-term diffs are now persisted and can
   separate the two.

## Limitations

- Synthetic TTS, two voices, 4 calls, no real customer audio.
- The oracle is built from the assignment’s expected terms, not from a
  customer-supplied must-have list.
- WER is high and format-sensitive; do not quote it as recognition quality.
- n=4 is descriptive; no confirmatory claim.

## Next

1. Run the per-term diff on these persisted transcripts to classify lost real
   terms as absent, substituted, or spelling variants.
2. Run the 20-call corpus (c00–c19) with the same six arms; only then can the
   H1/H2 tests reject.
3. Replace synthetic audio with 4–20 consented Hinglish calls.
