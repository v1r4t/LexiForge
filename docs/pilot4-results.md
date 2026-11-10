# Pilot 4 — six-arm synthetic result

**Scope:** Hinglish banking, synthetic TTS audio, 4 calls (c00–c03), 5 turns each,
`format=transliterate`, `language_code=hi-IN,en-IN`, budget 200.
**The selected arm was brand-only, 8–9 terms — not a 200-term list.**
**Internal harness validation — not customer evidence.**

## Arms

| Arm | Real recall | Fictional-name recall | Insertions / utterance | WER |
|---|---|---|---|---|
| baseline | 21/23 (91.3%) | 2/12 (16.7%) | 0.00 | 27.2% |
| selected (brand-only, 8–9 terms; not 200) | 16/23 (69.6%) | 10/12 (83.3%) | 0.05 | 41.8% |
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
  **+9.17pp**, 95% CI [0.0, +18.3]; direction consistent, **CI touches zero**.
- **Pilot verdict** — selected vs baseline on the B guardrail: real recall
  **−22.5pp**, 95% CI [−36.7, −8.3]; **FAIL** under the −5pp margin.
- **MDE not reported at n=4**; the design target is roughly 20pp at n=20.
- **Claim ladder:** mechanism only.

n=4 cannot reject at the pre-registered family: the smallest attainable
one-sided sign-flip p-value is 1/16 = 0.0625. The direction is consistent; the
sample is not.

## Findings

1. **Every keyterm list lowered real recall vs baseline**, including the oracle
   (82.6% vs 91.3%). The positive control is directionally consistent because
   oracle beats mismatched, though its CI touches zero.
2. **Fictional-name recall behaves as intended**: oracle 100%, selected 83.3%,
   baseline 16.7%.
3. **Selected brand-only list is not free**: real recall −22.5pp vs baseline,
   insertions +0.05.
4. **The trade-off is the result**, not a selector bug. It may still be partly a
   transliteration/alias artefact; per-term diffs are now persisted and can
   separate the two.
5. **Open question:** ASR bias or romanisation drift? Gnani has not measured
   transliterated-output accuracy, and the matcher has no transliteration; Hindi
   terms rely on pre-written romanised aliases. This is the leading confound.

## Limitations

- Synthetic TTS, two voices, 4 calls, no real customer audio.
- **`format=transliterate`**: Gnani has not measured transliterated-output
  accuracy; the matcher has no transliteration and relies on pre-written
  romanised aliases. This is a likely confound, not just a pipeline detail.
- **The selected arm was 8–9 brand-only terms, not a 200-term list.** The
  200-term selector was not tested in this pilot.
- The oracle is built from the assignment’s expected terms, not from a
  customer-supplied must-have list.
- Telephony processing (8 kHz, G.711, noise) exists in the repo, but was not
  verified as applied to this pilot’s audio.
- WER is high and format-sensitive; do not quote it as recognition quality.
- n=4 is descriptive; no confirmatory claim.

## Next

1. Run the per-term diff on these persisted transcripts to classify lost real
   terms as absent, substituted, or spelling variants.
2. Run the 20-call corpus (c00–c19) with the same six arms; only then can the
   H1/H2 tests reject.
3. Replace synthetic audio with 4–20 consented Hinglish calls.
